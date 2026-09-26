import logging
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..agents import run_queue
from ..auth import current_user
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import Dispute, JuryVote, User
from ..schemas import DisputeCreateIn, DisputeOut, JuryVoteIn
from ..services import gemini, worker
from .cases import _load
from .world import verify_and_record

log = logging.getLogger(__name__)
router = APIRouter(tags=["jury"])


def _request_summary(db: Session, d: Dispute, bg: BackgroundTasks) -> None:
    """紛争の論点整理を始める。既定は AG-001 → AG-004 経由（WP-019。ランナーの実行 → apply_dispute で summary_json に写す）。
    AGENT_PIPELINE=legacy なら旧経路（_summarize_job。summarize_dispute を BackgroundTasks で実行）。"""
    if get_settings().agent_pipeline == "legacy":
        bg.add_task(_summarize_job, d.id)
    else:
        run_queue.request_dispute(db, d.id, input_text=d.reason)


def _summarize_job(dispute_id: str) -> None:
    """旧経路（AGENT_PIPELINE=legacy のときだけ使う）"""
    db = SessionLocal()
    try:
        d = db.get(Dispute, dispute_id)
        case = _load(db, d.case_id)
        try:
            s = gemini.summarize_dispute(
                case_title=case.title, case_description=case.description, plan_summary=(case.plan_json or {}).get("summary", ""),
                deliverables=[(t.title, t.deliverable or "") for t in case.tasks], reason=d.reason,
            )
            d.summary_json = s.model_dump()
        except Exception as e:  # noqa: BLE001
            log.exception("summary failed")
            d.summary_json = {"error": str(e)}
        db.commit()
    finally:
        db.close()


@router.post("/cases/{case_id}/dispute", response_model=DisputeOut, status_code=201)
def open_dispute(case_id: str, body: DisputeCreateIn, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = _load(db, case_id)
    if case.client_id != user.id:
        raise HTTPException(403)
    if case.status not in ("delivered", "in_progress"):
        raise HTTPException(400, "進行中または納品済みの案件のみ差し戻せます")
    d = Dispute(case_id=case.id, reason=body.reason, status="open")
    case.status = "disputed"
    db.add(d)
    db.commit()
    db.refresh(d)
    # 未払いのタスクを保留（Disputed）にする。資金は動かない（FR-013）
    for t in case.tasks:
        if t.chain_status in ("funded", "submitted"):
            worker.enqueue(db, "dispute", f"dispute:{t.id}:{d.id}", {"task_db_id": t.id, "case_id_hex": case.escrow_case_id, "task_id_hex": t.escrow_task_id})
    _request_summary(db, d, bg)
    return d


@router.get("/disputes", response_model=list[DisputeOut])
def list_disputes(status: str | None = "open", db: Session = Depends(get_db)):
    q = db.query(Dispute)
    if status:
        q = q.filter(Dispute.status == status)
    return q.order_by(Dispute.created_at.desc()).all()


@router.get("/disputes/{dispute_id}", response_model=DisputeOut)
def get_dispute(dispute_id: str, db: Session = Depends(get_db)):
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise HTTPException(404)
    return d


@router.post("/disputes/{dispute_id}/vote", response_model=DisputeOut)
def vote(dispute_id: str, body: JuryVoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise HTTPException(404)
    if d.status != "open":
        raise HTTPException(400, "この紛争は終了しています")
    case = _load(db, d.case_id)
    parties = {case.client_id, case.agent.creator_id} | {t.human_task.worker_id for t in case.tasks if t.human_task and t.human_task.worker_id}
    if user.id in parties:
        raise HTTPException(403, "当事者は投票できません")
    if any(v.voter_id == user.id for v in d.votes):
        raise HTTPException(409, "既に投票済みです")
    nullifier = verify_and_record(db, user, action="jury", signal=d.id, idkit_response=body.idkit_response)
    d.votes.append(JuryVote(voter_id=user.id, vote=body.vote, nullifier=nullifier))
    db.commit()
    db.refresh(d)

    if len(d.votes) >= d.required_votes:
        counts = Counter(v.vote for v in d.votes)
        outcome = "release" if counts["release"] > counts["refund"] else "refund"
        # 裁定に基づく資金解放（FR-019）: タスクごとに worker が resolve を送る。支払先が無い（未提出）タスクは返金
        jobs = []
        for t in case.tasks:
            if t.chain_status not in ("disputed", "funded", "submitted"):
                continue
            amt = int(t.estimated_cost)
            pay = amt if (outcome == "release" and t.payee) else 0
            job = worker.enqueue(db, "resolve", f"resolve:{t.id}:{d.id}", {"task_db_id": t.id, "case_id_hex": case.escrow_case_id, "task_id_hex": t.escrow_task_id, "pay_amount": str(pay), "refund_amount": str(amt - pay)})
            if job:
                jobs.append(job.id)
        d.outcome, d.status, d.resolve_tx_hash = outcome, "closed", None
        d.summary_json = {**(d.summary_json or {}), "resolve_jobs": jobs}
        db.commit()
        db.refresh(d)
    return d
