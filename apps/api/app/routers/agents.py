import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException  # noqa: F401
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..models import Agent, Review, User
from ..schemas import AgentCreateIn, AgentDetailOut, AgentOut, ReviewOut, TxIn
from ..services import ens, worker

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


def profile_texts(agent: Agent, avatar: str | None = None) -> dict[str, str]:
    s = get_settings()
    t = {
        "description": agent.description,
        "url": f"{s.app_url}/agents/{agent.id}",
        "codrea.agent.category": agent.category,
        "codrea.agent.fee_bps": str(agent.fee_bps),
        "codrea.agent.creator": agent.creator.wallet_address,
        "codrea.agent.endpoint": f"{s.api_url}/agents/{agent.id}",
        "codrea.agent.rating": f"{float(agent.rating_avg):.1f}",
        "codrea.agent.reviews": str(agent.rating_count),
        "codrea.agent.completed": str(agent.completed_count),
    }
    if avatar:
        t["avatar"] = avatar
    if agent.owner_mode == "creator":
        t["codrea.agent.creator"] = agent.parent_ens_name or agent.creator.wallet_address
    return t


def ens_update_job(db: Session, agent: Agent, texts: dict[str, str]) -> None:
    """ENS の text record 更新を worker に投入する（値ごとに冪等）。
    Creator 所有の名前はプラットフォームに書き込み権限が無いため DB のみ更新（EAC で Reputation 役割を委任するまでの暫定）"""
    if agent.owner_mode == "creator":
        return
    key = "ens_update:" + agent.label + ":" + ",".join(f"{k}={v}" for k, v in sorted(texts.items()))
    worker.enqueue(db, "ens_update", key[:200], {"label": agent.label, "texts": texts})


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
    parent, mode = None, "platform"
    if body.parent_ens_name:
        # D1: Creator 自身の .eth の下に公開する。所有者が接続ウォレットか ENSv2 で確認（RPC 未設定時は通す）
        owner = ens.name_owner(body.parent_ens_name)
        if owner is not None and owner.lower() != user.wallet_address:
            raise HTTPException(403, f"{body.parent_ens_name} の所有者（{owner}）が接続中のウォレットと一致しません")
        parent, mode = body.parent_ens_name, "creator"
    agent = Agent(
        creator_id=user.id, name=body.name, label=body.label, description=body.description, category=body.category,
        rules=body.rules, fee_bps=body.fee_bps, payout_address=(body.payout_address or user.wallet_address).lower(), status="draft",
        parent_ens_name=parent, owner_mode=mode,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/publish")
def publish_agent(agent_id: str, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """公開。platform: worker が choice.eth の下に発行。creator: Creator が署名する calldata を返す。"""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    if agent.creator_id != user.id:
        raise HTTPException(403)
    if agent.status == "published":
        return {"mode": agent.owner_mode, "agent": AgentOut.model_validate(agent)}
    if agent.owner_mode == "creator":
        name = f"{agent.label}.{agent.parent_ens_name}"
        if not get_settings().sepolia_rpc_url:
            agent.ens_name, agent.ens_tx_hash, agent.status = name, "0xmock" + agent.id.replace("-", "")[:26] + "00", "published"
            db.commit()
            db.refresh(agent)
            return {"mode": "creator", "mock": True, "txs": [], "agent": AgentOut.model_validate(agent)}
        try:
            txs = ens.member_calldata(company_name=agent.parent_ens_name, label=agent.label, owner=user.wallet_address, texts=profile_texts(agent))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e)) from e
        agent.status = "publishing"
        db.commit()
        db.refresh(agent)
        return {"mode": "creator", "mock": False, "txs": txs, "ens_name": name, "agent": AgentOut.model_validate(agent)}
    agent.status = "publishing"
    agent.ens_error = None
    db.commit()
    db.refresh(agent)
    worker.enqueue(db, "ens_publish", f"ens_publish:{agent.id}:{agent.status}", {"agent_id": agent.id, "label": agent.label, "payout_address": agent.payout_address, "texts": profile_texts(agent)})
    return {"mode": "platform", "agent": AgentOut.model_validate(agent)}


@router.post("/{agent_id}/ens-written", response_model=AgentOut)
def agent_ens_written(agent_id: str, body: TxIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creator 所有の Agent: ブラウザで register / multicall を送った後に tx hash を報告する"""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.creator_id != user.id or agent.owner_mode != "creator":
        raise HTTPException(400, "対象の Agent ではありません")
    agent.ens_name, agent.ens_tx_hash, agent.status, agent.ens_error = f"{agent.label}.{agent.parent_ens_name}", body.tx_hash, "published", None
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    out = AgentDetailOut.model_validate(agent)
    if agent.ens_name and agent.owner_mode == "platform" and agent.ens_tx_hash and not agent.ens_tx_hash.startswith("0xmock"):
        out.ens_records = ens.read_texts(agent.ens_name)
        out.ens_reputation_name = ens.reputation_name(agent.label)
        out.ens_reputation_records = ens.read_texts(out.ens_reputation_name, ens.REPUTATION_KEYS)
        out.ens_roles = ens.agent_roles(agent.ens_name, agent.label)
    elif agent.ens_name:
        out.ens_records = ens.read_texts(agent.ens_name)
    return out


@router.get("/{agent_id}/reviews", response_model=list[ReviewOut])
def agent_reviews(agent_id: str, db: Session = Depends(get_db)):
    return db.query(Review).filter(Review.target_type == "agent", Review.target_id == agent_id).order_by(Review.created_at.desc()).all()
