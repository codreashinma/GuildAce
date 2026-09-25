import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..db import SessionLocal, get_db
from ..models import Agent, Case, Dispute, HumanTask, Task, User
from ..schemas import CaseCreateIn, CaseDetailOut, CaseOut, TxIn
from ..services import assign, chain, gemini, payouts
from ..services.gemini import USDC
from .agents import profile_texts
from ..services import ens

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", tags=["cases"])


def _load(db: Session, case_id: str) -> Case:
    case = (
        db.query(Case)
        .options(selectinload(Case.tasks).selectinload(Task.human_task).selectinload(HumanTask.worker), selectinload(Case.agent).selectinload(Agent.creator), selectinload(Case.client))
        .filter(Case.id == case_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(404, "案件が見つかりません")
    return case


def _detail(db: Session, case: Case) -> CaseDetailOut:
    out = CaseDetailOut.model_validate(case)
    if case.status in ("delivered", "completed", "resolved", "disputed"):
        out.split = payouts.compute_split(case)  # type: ignore[assignment]
    d = db.query(Dispute).filter(Dispute.case_id == case.id).order_by(Dispute.created_at.desc()).first()
    out.dispute_id = d.id if d else None
    return out


# ---------------------------------------------------------------- background jobs


def _plan_job(case_id: str) -> None:
    db = SessionLocal()
    try:
        case = _load(db, case_id)
        try:
            plan = gemini.plan_case(
                agent_name=case.agent.name, agent_rules=case.agent.rules, fee_bps=case.agent.fee_bps,
                title=case.title, description=case.description, budget_usdc=int(case.budget) // USDC, deadline=case.deadline,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("planning failed")
            case.status, case.error = "planning_failed", str(e)[:1000]
            db.commit()
            return
        case.plan_json = plan.model_dump()
        for i, t in enumerate(plan.tasks):
            member = next((m.name for m in plan.team if m.role == t.role), None) or (f"{t.role.title()} Agent" if t.type == "ai" else "Human Task Worker")
            db.add(Task(case_id=case.id, order_no=i, title=t.title, description=t.description, type=t.type, role=t.role,
                        estimated_cost=t.estimated_cost * USDC, assignee_name=member))
        case.status = "awaiting_approval"
        db.commit()
    finally:
        db.close()


def _execute_job(case_id: str) -> None:
    db = SessionLocal()
    try:
        case = _load(db, case_id)
        for t in case.tasks:
            if t.type == "human" and t.human_task is None:
                ht = HumanTask(task_id=t.id, case_id=case.id, title=t.title, description=t.description, reward=int(t.estimated_cost), status="open")
                db.add(ht)
                t.status = "in_progress"
                db.commit()
                db.refresh(ht)
                assign.assign(db, ht)  # PM Agent が ENS 上の人員から指名
        for t in case.tasks:
            if t.type != "ai" or t.status == "done":
                continue
            t.status = "in_progress"
            db.commit()
            try:
                t.deliverable = gemini.execute_ai_task(
                    agent_name=case.agent.name, agent_rules=case.agent.rules, case_title=case.title, case_description=case.description,
                    task_title=t.title, task_description=t.description, role=t.role,
                )
                t.status, t.completed_at = "done", datetime.now(UTC)
            except Exception as e:  # noqa: BLE001
                log.exception("task execution failed")
                t.deliverable = f"（生成に失敗しました: {e}）"
                t.status, t.completed_at = "done", datetime.now(UTC)
            db.commit()
        check_delivered(db, case)
    finally:
        db.close()


def check_delivered(db: Session, case: Case) -> None:
    db.refresh(case)
    if case.status == "in_progress" and all(t.status == "done" for t in case.tasks):
        case.status = "delivered"
        db.commit()


# ---------------------------------------------------------------- endpoints


@router.get("", response_model=list[CaseOut])
def list_cases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Case).filter(Case.client_id == user.id).order_by(Case.created_at.desc()).all()


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreateIn, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = db.get(Agent, body.agent_id)
    if agent is None or agent.status != "published":
        raise HTTPException(400, "公開済みの PM Agent を選んでください")
    case = Case(client_id=user.id, agent_id=agent.id, title=body.title, description=body.description,
                budget=body.budget_usdc * USDC, deadline=body.deadline, status="planning", escrow_case_id="")
    db.add(case)
    db.flush()
    case.escrow_case_id = chain.escrow_case_id(case.id)
    db.commit()
    bg.add_task(_plan_job, case.id)
    return _load(db, case.id)


@router.get("/{case_id}", response_model=CaseDetailOut)
def get_case(case_id: str, db: Session = Depends(get_db)):
    return _detail(db, _load(db, case_id))


@router.post("/{case_id}/replan", response_model=CaseOut)
def replan(case_id: str, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = _load(db, case_id)
    if case.client_id != user.id:
        raise HTTPException(403)
    if case.status not in ("planning_failed", "awaiting_approval"):
        raise HTTPException(400, "この状態では再計画できません")
    for t in case.tasks:
        db.delete(t)
    case.status, case.error, case.plan_json = "planning", None, None
    db.commit()
    bg.add_task(_plan_job, case.id)
    return _load(db, case.id)


@router.post("/{case_id}/funded", response_model=CaseDetailOut)
def funded(case_id: str, body: TxIn, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """発注者が Escrow.deposit を送った後、tx hash を受け取って検証し、実行を開始する。"""
    case = _load(db, case_id)
    if case.client_id != user.id:
        raise HTTPException(403)
    if case.status != "awaiting_approval":
        raise HTTPException(400, "承認待ちの案件ではありません")
    try:
        chain.verify_event(body.tx_hash, "Deposited", case.escrow_case_id, client=user.wallet_address, amount=int(case.budget))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"入金を確認できません: {e}") from e
    case.deposit_tx_hash = body.tx_hash
    case.status = "in_progress"
    db.commit()
    bg.add_task(_execute_job, case.id)
    return _detail(db, _load(db, case.id))


@router.post("/{case_id}/released", response_model=CaseDetailOut)
def released(case_id: str, body: TxIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """発注者が Escrow.release に署名した後、tx hash を検証して完了にする。"""
    case = _load(db, case_id)
    if case.client_id != user.id:
        raise HTTPException(403)
    if case.status != "delivered":
        raise HTTPException(400, "納品済みの案件ではありません")
    try:
        chain.verify_event(body.tx_hash, "Released", case.escrow_case_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"支払いを確認できません: {e}") from e
    case.release_tx_hash = body.tx_hash
    case.status = "completed"
    agent = case.agent
    agent.completed_count += 1
    db.commit()
    try:
        ens.update_texts(agent.label, {"agent.completed": str(agent.completed_count)})
    except Exception:  # noqa: BLE001
        log.exception("ENS completed update failed")
    return _detail(db, _load(db, case.id))
