"""取引オーケストレーション（CMP-003）。依頼 → 計画 → openCase → 工程ごとの預託 → 実行・提出 → 承認 → 自動支払い。
オンチェーンへの書き込みは worker.enqueue で投入するだけ（ADR-006）。"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import Agent, Approval, Case, Dispute, HumanTask, Task, User
from ..schemas import ApproveIn, CaseCreateIn, CaseDetailOut, CaseOpenedIn, CaseOut, NoticeOut, PendingApprovalOut, TaskOut
from ..services import assign, chain, gemini, worker
from ..services.gemini import USDC
from .world import verify_and_record

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", tags=["cases"])


def _load(db: Session, case_id: str) -> Case:
    case = (
        db.query(Case)
        .options(
            selectinload(Case.tasks).selectinload(Task.human_task).selectinload(HumanTask.worker),
            selectinload(Case.tasks).selectinload(Task.human_task).selectinload(HumanTask.assignee),
            selectinload(Case.tasks).selectinload(Task.approvals).selectinload(Approval.approver),
            selectinload(Case.agent).selectinload(Agent.creator),
            selectinload(Case.client),
        )
        .filter(Case.id == case_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(404, "案件が見つかりません")
    return case


def _detail(db: Session, case: Case) -> CaseDetailOut:
    out = CaseDetailOut.model_validate(case)
    d = db.query(Dispute).filter(Dispute.case_id == case.id).order_by(Dispute.created_at.desc()).first()
    out.dispute_id = d.id if d else None
    return out


def project_label(case: Case) -> str:
    return f"project-{int(case.id.replace('-', '')[:6], 16) % 1000}"


# ---------------------------------------------------------------- status projection


def after_chain_update(db: Session, case_id: str) -> None:
    """タスクのオンチェーン投影から案件の状態を導く。資金の正本はコントラクト側（ADR-001）。"""
    case = _load(db, case_id)
    if case.status in ("planning", "planning_failed", "awaiting_approval", "draft"):
        return
    st = [t.chain_status for t in case.tasks]
    if not st:
        return
    if all(s_ in ("paid", "resolved") for s_ in st):
        new = "resolved" if any(s_ == "resolved" for s_ in st) else "completed"
    elif any(s_ == "disputed" for s_ in st):
        new = "disputed"
    elif all(t.status == "done" for t in case.tasks):
        new = "delivered"  # 全タスク提出済み、承認待ち
    else:
        new = "in_progress"
    if new != case.status:
        was = case.status
        case.status = new
        db.commit()
        if new == "completed" and was != "completed":
            _on_completed(db, case)


def _on_completed(db: Session, case: Case) -> None:
    agent = case.agent
    agent.completed_count += 1
    db.commit()
    from .agents import ens_update_job

    ens_update_job(db, agent, {"agent.completed": str(agent.completed_count)})
    worker.enqueue(db, "ens_update", f"ens_project_status:{case.id}:completed",
                   {"label": f"{project_label(case)}.{case.agent.label}", "texts": {"project.status": "completed"}}) if case.project_ens_name else None


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
        total = 0
        for i, t in enumerate(plan.tasks):
            member = next((m.name for m in plan.team if m.role == t.role), None) or (f"{t.role.title()} Agent" if t.type == "ai" else "Human Task Worker")
            task = Task(case_id=case.id, order_no=i, title=t.title, description=t.description, type=t.type, role=t.role,
                        estimated_cost=t.estimated_cost * USDC, assignee_name=member)
            db.add(task)
            total += t.estimated_cost * USDC
        # PM 管理費もタスク（工程）として契約する（CON-006、Creator の収益）
        fee = int(case.budget) - total
        db.add(Task(case_id=case.id, order_no=len(plan.tasks), title="PM 管理（タスク分解・チーム編成・進捗管理）", description=plan.summary,
                    type="ai", role="pm", estimated_cost=fee, assignee_name=case.agent.name))
        db.flush()
        for t in db.query(Task).filter(Task.case_id == case.id):
            t.escrow_task_id = chain.escrow_task_id(t.id)
        case.status = "awaiting_approval"
        db.commit()
    finally:
        db.close()


def _submit_task(db: Session, case: Case, t: Task, payee: str) -> None:
    """成果物のハッシュと支払先をオンチェーンへ（worker 経由）"""
    t.deliverable_hash = chain.deliverable_hash(t.deliverable or "")
    t.payee = payee.lower()
    db.commit()
    worker.enqueue(db, "submit", f"submit:{t.id}:{t.deliverable_hash}", {
        "task_db_id": t.id, "case_id_hex": case.escrow_case_id, "task_id_hex": t.escrow_task_id, "deliverable_hash": t.deliverable_hash, "payee": t.payee,
    })


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
                assign.assign(db, ht)  # PM Agent が ENS 上の人員から指名（FR-004/FR-020）
        for t in case.tasks:
            if t.type != "ai" or t.status == "done":
                continue
            t.status = "in_progress"
            db.commit()
            try:
                if t.role == "pm":
                    t.deliverable = f"# PM 管理レポート\n\n{(case.plan_json or {}).get('summary', '')}\n\n" + "\n".join(f"- {x.title}（{x.assignee_name}）" for x in case.tasks if x.role != "pm")
                else:
                    t.deliverable = gemini.execute_ai_task(
                        agent_name=case.agent.name, agent_rules=case.agent.rules, case_title=case.title, case_description=case.description,
                        task_title=t.title, task_description=t.description, role=t.role,
                    )
            except Exception as e:  # noqa: BLE001
                log.exception("task execution failed")
                t.deliverable = f"（生成に失敗しました: {e}）"
            t.status, t.completed_at = "done", datetime.now(UTC)
            db.commit()
            _submit_task(db, case, t, case.agent.payout_address)
        after_chain_update(db, case.id)
    finally:
        db.close()


def submit_human_task(db: Session, ht: HumanTask) -> None:
    """Human Task の提出をオンチェーンへ（human_tasks router から呼ぶ）"""
    case = _load(db, ht.case_id)
    t = next(x for x in case.tasks if x.id == ht.task_id)
    _submit_task(db, case, t, ht.worker.wallet_address)
    after_chain_update(db, case.id)


# ---------------------------------------------------------------- endpoints


@router.get("", response_model=list[CaseOut])
def list_cases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    mine = db.query(Case).filter(Case.client_id == user.id)
    # 承認者として関わる案件も含める
    approver_cases = [c for c in db.query(Case).filter(Case.approvers.isnot(None)) if user.wallet_address in [a.lower() for a in (c.approvers or [])] and c.client_id != user.id]
    return sorted([*mine, *approver_cases], key=lambda c: c.created_at, reverse=True)


def _approver_cases(db: Session, user: User) -> list[Case]:
    return [c for c in db.query(Case).filter(Case.approvers.isnot(None)) if user.wallet_address in [a.lower() for a in (c.approvers or [])]]


@router.get("/pending-approvals", response_model=list[PendingApprovalOut])
def pending_approvals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """C1: 自分の署名待ちの工程（承認者として関わる案件を横断）"""
    out = []
    for c in _approver_cases(db, user):
        if c.status not in ("in_progress", "delivered"):
            continue
        case = _load(db, c.id)
        for t in case.tasks:
            if t.chain_status != "submitted" or t.status != "done":
                continue
            if any(a.approver_id == user.id and a.deliverable_hash == t.deliverable_hash for a in t.approvals):
                continue
            out.append(PendingApprovalOut(case_id=case.id, case_title=case.title, task_id=t.id, task_title=t.title, task_type=t.type, amount=int(t.estimated_cost),
                                          approval_count=t.approval_count, threshold=case.threshold, payee=t.payee, deliverable_hash=t.deliverable_hash))
    return out


@router.get("/notifications", response_model=list[NoticeOut])
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A2: 関係者への通知（FR-032）。承認待ち・指名・提出・支払い・紛争を横断して返す"""
    from ..models import HumanTask, Member

    out: list[NoticeOut] = []
    for p in pending_approvals(user, db):
        out.append(NoticeOut(id=f"approve:{p.task_id}:{p.deliverable_hash}", kind="approve", urgent=True,
                             title=f"承認をお願いします（{p.approval_count}/{p.threshold}）", body=f"{p.case_title} / {p.task_title}", href=f"/cases/{p.case_id}"))
    member_ids = [m.id for m in db.query(Member).filter(Member.wallet_address == user.wallet_address)]
    if member_ids:
        for ht in db.query(HumanTask).filter(HumanTask.status == "assigned", HumanTask.assignee_member_id.in_(member_ids)):
            out.append(NoticeOut(id=f"assigned:{ht.id}", kind="assigned", urgent=True, title="PM Agent から指名されました", body=ht.title, href=f"/tasks/{ht.id}"))
    for c in db.query(Case).filter(Case.client_id == user.id).order_by(Case.created_at.desc()).limit(20):
        if c.status == "awaiting_approval":
            out.append(NoticeOut(id=f"open:{c.id}", kind="approve", urgent=True, title="計画の承認と Escrow の開設をお願いします", body=c.title, href=f"/cases/{c.id}"))
        elif c.status == "disputed":
            out.append(NoticeOut(id=f"dispute:{c.id}", kind="dispute", urgent=True, title="紛争が発生しました。Jury の裁定待ちです", body=c.title, href=f"/cases/{c.id}"))
        elif c.status == "completed":
            out.append(NoticeOut(id=f"paid:{c.id}", kind="pay", title="全工程の支払いが Escrow から実行されました", body=c.title, href=f"/cases/{c.id}"))
        elif c.status in ("in_progress", "delivered"):
            paid = sum(1 for t in c.tasks if t.chain_status == "paid")
            sub = sum(1 for t in c.tasks if t.chain_status == "submitted")
            if sub:
                out.append(NoticeOut(id=f"deliver:{c.id}:{sub}", kind="deliver", title=f"{sub} 工程の成果物が提出されています", body=c.title, href=f"/cases/{c.id}"))
            if paid:
                out.append(NoticeOut(id=f"paid:{c.id}:{paid}", kind="pay", title=f"{paid} 工程の支払いが実行されました", body=c.title, href=f"/cases/{c.id}"))
    return out


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreateIn, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = db.get(Agent, body.agent_id)
    if agent is None or agent.status != "published":
        raise HTTPException(400, "公開済みの PM Agent を選んでください")
    case_id = str(uuid.uuid4())
    # FR-002: 依頼の開始は World で人間性を確認する（signal = 依頼ごとの ID）
    nullifier = verify_and_record(db, user, action="request", signal=case_id, idkit_response=body.idkit_response)
    approvers = [a.lower() for a in body.approvers] or [user.wallet_address]
    if body.threshold > len(approvers):
        raise HTTPException(400, "必要承認数が承認者数を超えています")
    case = Case(id=case_id, client_id=user.id, agent_id=agent.id, title=body.title, description=body.description,
                budget=body.budget_usdc * USDC, deadline=body.deadline, status="planning", escrow_case_id=chain.escrow_case_id(case_id),
                approvers=approvers, threshold=body.threshold, request_nullifier=nullifier)
    db.add(case)
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


@router.post("/{case_id}/opened", response_model=CaseDetailOut)
def opened(case_id: str, body: CaseOpenedIn, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """発注者が Escrow.openCase（承認者の固定）と USDC の approve を済ませたら、工程ごとの預託を worker に要求する（IF-008）。"""
    case = _load(db, case_id)
    if case.client_id != user.id:
        raise HTTPException(403)
    if case.status != "awaiting_approval":
        raise HTTPException(400, "承認待ちの案件ではありません")
    try:
        chain.verify_case_opened(body.tx_hash, case.escrow_case_id, user.wallet_address, case.approvers or [], case.threshold)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"openCase を確認できません: {e}") from e
    case.open_tx_hash = body.tx_hash
    case.status = "in_progress"
    db.commit()
    for t in case.tasks:
        worker.enqueue(db, "fund_task", f"fund:{t.id}", {"task_db_id": t.id, "case_id_hex": case.escrow_case_id, "task_id_hex": t.escrow_task_id, "amount": str(int(t.estimated_cost))})
    s = get_settings()
    worker.enqueue(db, "ens_project", f"ens_project:{case.id}", {
        "case_db_id": case.id, "agent_label": case.agent.label, "project_label": project_label(case),
        "agent_mock": not case.agent.ens_tx_hash or case.agent.ens_tx_hash.startswith("0xmock") or case.agent.owner_mode == "creator",
        "texts": {"description": case.title, "project.case": case.id, "project.escrow": s.escrow_address or "mock", "project.escrow_case_id": case.escrow_case_id,
                  "project.client": user.wallet_address, "project.status": "in_progress", "url": f"{s.app_url}/cases/{case.id}"},
    })
    bg.add_task(_execute_job, case.id)
    return _detail(db, _load(db, case.id))


@router.get("/{case_id}/tasks/{task_id}/typed-data")
def approval_typed_data(case_id: str, task_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = _load(db, case_id)
    t = next((x for x in case.tasks if x.id == task_id), None)
    if t is None or not t.deliverable_hash or not t.payee:
        raise HTTPException(400, "このタスクはまだ提出されていません")
    return chain.approval_typed_data(case.escrow_case_id, t.escrow_task_id, t.deliverable_hash, t.payee)


@router.post("/{case_id}/tasks/{task_id}/approve", response_model=TaskOut)
def approve_task(case_id: str, task_id: str, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """承認者が World で人間確認（FR-011）し、EIP-712 で (成果物ハッシュ, 支払先) に署名する。worker がオンチェーンへ中継し、必要数で自動支払い。"""
    case = _load(db, case_id)
    t = next((x for x in case.tasks if x.id == task_id), None)
    if t is None:
        raise HTTPException(404)
    if user.wallet_address not in [a.lower() for a in (case.approvers or [])]:
        raise HTTPException(403, "この案件の承認者ではありません")
    if t.status != "done" or not t.deliverable_hash or not t.payee:
        raise HTTPException(400, "成果物が提出されていません")
    if t.chain_status not in ("submitted", "funded"):
        raise HTTPException(400, f"この状態では承認できません（{t.chain_status}）")
    if any(a.approver_id == user.id and a.deliverable_hash == t.deliverable_hash for a in t.approvals):
        raise HTTPException(409, "この成果物は承認済みです")
    typed = chain.approval_typed_data(case.escrow_case_id, t.escrow_task_id, t.deliverable_hash, t.payee)
    if chain.recover_approval_signer(typed, body.signature).lower() != user.wallet_address:
        raise HTTPException(400, "署名が承認者のものではありません")
    nullifier = verify_and_record(db, user, action="approve", signal=f"{t.id}:{t.deliverable_hash}", idkit_response=body.idkit_response)
    db.add(Approval(task_id=t.id, approver_id=user.id, deliverable_hash=t.deliverable_hash, signature=body.signature, nullifier=nullifier))
    db.commit()
    count_after = sum(1 for a in t.approvals if a.deliverable_hash == t.deliverable_hash) + 1
    worker.enqueue(db, "approve", f"approve:{t.id}:{t.deliverable_hash}:{user.wallet_address}", {
        "task_db_id": t.id, "case_id_hex": case.escrow_case_id, "task_id_hex": t.escrow_task_id, "deliverable_hash": t.deliverable_hash,
        "payee": t.payee, "approver": user.wallet_address, "signature": body.signature, "approval_count_after": count_after, "threshold": case.threshold,
    })
    db.refresh(t)
    return t


@router.post("/{case_id}/resync", response_model=CaseDetailOut)
def resync(case_id: str, db: Session = Depends(get_db)):
    """オンチェーンの正本から投影を取り直す（イベント取りこぼし対策、AQ-007 の簡易版）"""
    case = _load(db, case_id)
    for t in case.tasks:
        if not t.escrow_task_id:
            continue
        on = chain.read_task(case.escrow_case_id, t.escrow_task_id)
        if on and on["status"] != "none":
            t.chain_status, t.approval_count = on["status"], on["approval_count"]
            if int(on["payee"], 16):
                t.payee = on["payee"].lower()
    db.commit()
    after_chain_update(db, case.id)
    return _detail(db, _load(db, case.id))
