import logging
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import SessionLocal, get_db
from ..models import Dispute, JuryVote, User
from ..schemas import DisputeCreateIn, DisputeOut, JuryVoteIn
from ..services import chain, gemini, payouts
from .cases import _load
from .world import verify_and_record

log = logging.getLogger(__name__)
router = APIRouter(tags=["jury"])


def _summarize_job(dispute_id: str) -> None:
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
    if case.status != "delivered":
        raise HTTPException(400, "納品済みの案件のみ差し戻せます")
    d = Dispute(case_id=case.id, reason=body.reason, status="open")
    case.status = "disputed"
    db.add(d)
    db.commit()
    db.refresh(d)
    bg.add_task(_summarize_job, d.id)
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
        split = payouts.compute_split(case) if outcome == "release" else payouts.refund_split(case)
        try:
            tx = chain.send_resolve(case.escrow_case_id, [s["address"] for s in split], [int(s["amount"]) for s in split])
        except Exception as e:  # noqa: BLE001
            log.exception("resolve failed")
            raise HTTPException(500, f"Escrow の resolve に失敗しました: {e}") from e
        d.outcome, d.resolve_tx_hash, d.status = outcome, tx, "closed"
        case.status = "resolved"
        db.commit()
        db.refresh(d)
    return d
