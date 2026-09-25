import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import Agent, Review, User
from ..schemas import AgentCreateIn, AgentDetailOut, AgentOut, ReviewOut
from ..services import ens

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


def profile_texts(agent: Agent, avatar: str | None = None) -> dict[str, str]:
    s = get_settings()
    t = {
        "description": agent.description,
        "url": f"{s.app_url}/agents/{agent.id}",
        "agent.category": agent.category,
        "agent.fee_bps": str(agent.fee_bps),
        "agent.creator": agent.creator.wallet_address,
        "agent.endpoint": f"{s.api_url}/agents/{agent.id}",
        "agent.rating": f"{float(agent.rating_avg):.1f}",
        "agent.reviews": str(agent.rating_count),
        "agent.completed": str(agent.completed_count),
    }
    if avatar:
        t["avatar"] = avatar
    return t


def _publish_job(agent_id: str, avatar: str | None) -> None:
    db = SessionLocal()
    try:
        agent = db.get(Agent, agent_id)
        if agent is None:
            return
        try:
            name, tx = ens.publish_agent(label=agent.label, payout_address=agent.payout_address, texts=profile_texts(agent, avatar))
            agent.ens_name, agent.ens_tx_hash, agent.status, agent.ens_error = name, tx, "published", None
        except Exception as e:  # noqa: BLE001
            log.exception("ENS publish failed")
            agent.status, agent.ens_error = "publish_failed", str(e)[:1000]
        db.commit()
    finally:
        db.close()


@router.get("", response_model=list[AgentOut])
def list_agents(category: str | None = None, q: str | None = None, sort: str = "rating", db: Session = Depends(get_db)):
    query = db.query(Agent).filter(Agent.status == "published")
    if category:
        query = query.filter(Agent.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Agent.name.ilike(like), Agent.description.ilike(like), Agent.label.ilike(like)))
    order = {"rating": (Agent.rating_avg.desc(), Agent.rating_count.desc()), "completed": (Agent.completed_count.desc(),), "new": (Agent.created_at.desc(),)}
    return query.order_by(*order.get(sort, order["rating"])).all()


@router.get("/mine", response_model=list[AgentOut])
def my_agents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Agent).filter(Agent.creator_id == user.id).order_by(Agent.created_at.desc()).all()


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(body: AgentCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.query(Agent).filter(Agent.label == body.label).first():
        raise HTTPException(409, "このラベルは既に使われています")
    agent = Agent(
        creator_id=user.id, name=body.name, label=body.label, description=body.description, category=body.category,
        rules=body.rules, fee_bps=body.fee_bps, payout_address=(body.payout_address or user.wallet_address).lower(), status="draft",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/publish", response_model=AgentOut)
def publish_agent(agent_id: str, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    if agent.creator_id != user.id:
        raise HTTPException(403)
    if agent.status == "published":
        return agent
    agent.status = "publishing"
    agent.ens_error = None
    db.commit()
    db.refresh(agent)
    bg.add_task(_publish_job, agent.id, None)
    return agent


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    out = AgentDetailOut.model_validate(agent)
    if agent.ens_name:
        out.ens_records = ens.read_texts(agent.ens_name)
    return out


@router.get("/{agent_id}/reviews", response_model=list[ReviewOut])
def agent_reviews(agent_id: str, db: Session = Depends(get_db)):
    return db.query(Review).filter(Review.target_type == "agent", Review.target_id == agent_id).order_by(Review.created_at.desc()).all()
