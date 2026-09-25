import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Agent, HumanTask, Review, User
from ..schemas import ReviewCreateIn, ReviewOut
from .cases import _load
from .world import verify_and_record

log = logging.getLogger(__name__)
router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewOut, status_code=201)
def create_review(body: ReviewCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = _load(db, body.case_id)
    if case.status not in ("completed", "resolved"):
        raise HTTPException(400, "完了した案件のみレビューできます")
    is_client = case.client_id == user.id
    is_worker = any(t.human_task and t.human_task.worker_id == user.id for t in case.tasks)
    if not (is_client or is_worker):
        raise HTTPException(403, "案件の当事者のみレビューできます")
    # 発注者 → PM Agent、Human Task worker → 発注者
    target_type, target_id = ("agent", case.agent_id) if is_client else ("user", case.client_id)
    nullifier = verify_and_record(db, user, action="review", signal=case.id, idkit_response=body.idkit_response)
    review = Review(case_id=case.id, reviewer_id=user.id, target_type=target_type, target_id=target_id, rating=body.rating, comment=body.comment, nullifier=nullifier)
    db.add(review)
    db.commit()
    if target_type == "agent":
        agent = db.get(Agent, target_id)
        avg, cnt = db.query(func.avg(Review.rating), func.count(Review.id)).filter(Review.target_type == "agent", Review.target_id == agent.id).one()
        agent.rating_avg, agent.rating_count = round(float(avg or 0), 1), int(cnt)
        db.commit()
        from .agents import ens_update_job

        ens_update_job(db, agent, {"codrea.agent.rating": f"{float(agent.rating_avg):.1f}", "codrea.agent.reviews": str(agent.rating_count)})
    db.refresh(review)
    return review


@router.get("/case/{case_id}", response_model=list[ReviewOut])
def case_reviews(case_id: str, db: Session = Depends(get_db)):
    return db.query(Review).filter(Review.case_id == case_id).order_by(Review.created_at.desc()).all()
