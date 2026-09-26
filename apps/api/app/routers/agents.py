import hashlib
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException  # noqa: F401
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..models import Agent, Case, ChainJob, Review, Task, User
from ..schemas import AgentCreateIn, AgentDetailOut, AgentEarningsOut, AgentOut, AgentUpdateIn, EarningRowOut, ReviewOut, TxIn
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


def agent_subagents(agent: Agent) -> list[dict]:
    """所有者が定義した専門エージェントの一覧。未設定（None）は既定の 4 つ"""
    return [dict(x) for x in (agent.subagents if agent.subagents is not None else ens.DEFAULT_SUBAGENTS)]


def agent_on_ens(agent: Agent) -> bool:
    """ENS 上に実在する（モック公開でない）Agent か。Creator 所有はサブレジストリ（名前空間）が確認できたものだけ"""
    real = bool(agent.ens_tx_hash and not agent.ens_tx_hash.startswith("0xmock"))
    return real and (agent.owner_mode == "platform" or bool(agent.ens_subregistry))


def ens_update_job(db: Session, agent: Agent, texts: dict[str, str]) -> None:
    """ENS の text record 更新を worker に投入する（値ごとに冪等）。
    Creator 所有の名前はプロフィールを Creator しか書けないので、Reputation 鍵が書ける評価キー（reputation.<agent>）だけを投入する"""
    if agent.owner_mode == "creator":
        if not agent.ens_subregistry:
            return
        texts = {k: v for k, v in texts.items() if k in ens.REPUTATION_KEYS}
        if not texts:
            return
    key = "ens_update:" + agent.id + ":" + ",".join(f"{k}={v}" for k, v in sorted(texts.items()))
    payload = {"label": agent.label, "texts": texts}
    if agent.owner_mode == "creator":
        payload["agent_name"] = agent.ens_name
    worker.enqueue(db, "ens_update", key[:200], payload)


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
    parent, mode = None, "platform"
    if db.query(Agent).filter(Agent.label == body.label, func.coalesce(Agent.parent_ens_name, "") == (body.parent_ens_name or "")).first():
        raise HTTPException(409, f"{body.label}.{body.parent_ens_name or get_settings().ens_parent_name} is already taken")
    if body.parent_ens_name:
        # D1: Creator 自身の .eth の下に公開する。所有者が接続ウォレットか ENSv2 で確認する。
        # 未登録・RPC エラーは拒否（RPC 未設定 = モックのときだけ確認なしで通す）
        try:
            ens.require_owner(body.parent_ens_name, user.wallet_address)
        except ValueError as e:
            raise HTTPException(403, str(e)) from e
        parent, mode = body.parent_ens_name, "creator"
    agent = Agent(
        creator_id=user.id, name=body.name, label=body.label, description=body.description, category=body.category,
        rules=body.rules, fee_bps=body.fee_bps, payout_address=(body.payout_address or user.wallet_address).lower(), status="draft",
        parent_ens_name=parent, owner_mode=mode, policy=body.policy.model_dump() if body.policy else None,
        subagents=[x.model_dump() for x in body.subagents] if body.subagents is not None else None,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/publish")
def publish_agent(agent_id: str, bg: BackgroundTasks, subagents: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """公開。platform: worker が guildace.eth の下に発行。creator: Creator が署名する calldata（名前空間の構築込み）を返す。"""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    if agent.creator_id != user.id:
        raise HTTPException(403)
    if agent.status == "published" and (agent.owner_mode == "platform" or agent.ens_subregistry and not agent.ens_error):
        return {"mode": agent.owner_mode, "agent": AgentOut.model_validate(agent)}
    if agent.owner_mode == "creator":
        name = f"{agent.label}.{agent.parent_ens_name}"
        if not get_settings().sepolia_rpc_url:
            agent.ens_name, agent.ens_tx_hash, agent.status = name, "0xmock" + agent.id.replace("-", "")[:26] + "00", "published"
            db.commit()
            db.refresh(agent)
            return {"mode": "creator", "mock": True, "txs": [], "agent": AgentOut.model_validate(agent)}
        try:
            ns = ens.agent_namespace_calldata(name=name, owner=user.wallet_address, payout_address=agent.payout_address, texts=profile_texts(agent), subagents=agent_subagents(agent) if subagents else [])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e)) from e
        agent.status = "publishing"
        db.commit()
        db.refresh(agent)
        return {"mode": "creator", "mock": False, "txs": ns["txs"], "ens_name": name, "subregistry": ns["subregistry"], "reputation_name": ns["reputation_name"],
                "project_key": ns["project_key"], "reputation_key": ns["reputation_key"], "agent": AgentOut.model_validate(agent)}
    agent.status = "publishing"
    agent.ens_error = None
    db.commit()
    db.refresh(agent)
    worker.enqueue(db, "ens_publish", f"ens_publish:{agent.id}:{agent.status}", {"agent_id": agent.id, "label": agent.label, "payout_address": agent.payout_address, "texts": profile_texts(agent),
                                                                                  "subagents": agent_subagents(agent)})
    return {"mode": "platform", "agent": AgentOut.model_validate(agent)}


@router.post("/{agent_id}/ens-written", response_model=AgentOut)
def agent_ens_written(agent_id: str, body: TxIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creator 所有の Agent: ブラウザで register / multicall を送った後に tx hash を報告する"""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.creator_id != user.id or agent.owner_mode != "creator":
        raise HTTPException(400, "Not the target Agent")
    name = f"{agent.label}.{agent.parent_ens_name}"
    ens.invalidate_walk(name)  # Creator が今送った tx でリゾルバ・サブレジストリが変わっている可能性があるため、走査キャッシュを捨てる
    # 自己申告の tx hash を信用せず、レシートと text record をオンチェーンで確認する
    try:
        v = ens.verify_written(name=name, tx_hash=body.tx_hash, sender=user.wallet_address, key="codrea.agent.category")
    except ValueError as e:
        agent.ens_error = str(e)
        db.commit()
        raise HTTPException(400, str(e)) from e
    agent.ens_name, agent.ens_tx_hash, agent.status, agent.ens_error = name, body.tx_hash, "published", None
    if not v.get("mock"):
        # 名前空間（サブレジストリ・Project 鍵の権限・reputation subname）が揃っていれば記録し、評価 record の初期値を Reputation 鍵で書く
        try:
            ns = ens.verify_agent_namespace(name=name)
        except Exception as e:  # noqa: BLE001
            ns = {"subregistry": None, "error": str(e)[:120]}
        agent.ens_subregistry = ns.get("subregistry")
        if not ns.get("subregistry"):
            agent.ens_error = "Namespace (Subregistry) is not configured. Publish again to sign the remaining tx"
        elif not ns.get("reputation"):
            agent.ens_error = "Reputation subname has not been issued. Publish again to sign the remaining tx"
    db.commit()
    db.refresh(agent)
    if agent.ens_subregistry:
        ens_update_job(db, agent, {k: v for k, v in profile_texts(agent).items() if k in ens.REPUTATION_KEYS})
    return agent


@router.patch("/{agent_id}")
def update_agent(agent_id: str, body: AgentUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """D4: 説明・ルール・利用料などを更新し、ENS の text record を再書き込みする。
    platform: worker に ens_update を投入（Owner 鍵）。creator: Creator が署名する multicall の calldata を返す。"""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    if agent.creator_id != user.id:
        raise HTTPException(403, "Only the creator can edit this")
    before = profile_texts(agent)
    before_subs = {x["role"]: x for x in agent_subagents(agent)}
    changes = body.model_dump(exclude_none=True)
    avatar = changes.pop("avatar", None)
    new_subs = changes.pop("subagents", None)
    for k, v in changes.items():
        setattr(agent, k, v)
    if new_subs is not None:
        agent.subagents = new_subs
    db.flush()
    after = profile_texts(agent, avatar=avatar)
    diff = {k: v for k, v in after.items() if before.get(k) != v}
    out: dict = {"mode": agent.owner_mode, "changed_keys": sorted(diff)}
    # 専門エージェントの追加・変更（rules 以外）は ENS の subname / record に反映する。削除は ENS には触らない（record はそのまま残る）
    sub_changed = []
    if new_subs is not None:
        for x in new_subs:
            b = before_subs.get(x["role"])
            if b is None or any(b.get(k, "") != x.get(k, "") for k in ("name", "description")):
                sub_changed.append(x)
        out["changed_subagents"] = [x["role"] for x in sub_changed]
        out["removed_subagents"] = sorted(set(before_subs) - {x["role"] for x in new_subs})
    if sub_changed and agent.status == "published" and agent_on_ens(agent):
        if agent.owner_mode == "platform":
            key = "ens_subagents:" + agent.id + ":" + hashlib.sha256(repr(sorted((x["role"], x.get("name", ""), x.get("description", "")) for x in sub_changed)).encode()).hexdigest()[:16]
            worker.enqueue(db, "ens_subagents", key[:200], {"agent_id": agent.id, "label": agent.label, "subagents": sub_changed})
            out["ens_subagents"] = "queued"
        elif get_settings().sepolia_rpc_url:
            try:
                out["subagent_txs"] = ens.subagents_calldata(name=f"{agent.label}.{agent.parent_ens_name}", owner=user.wallet_address, subagents=sub_changed)
                out["ens_subagents"] = "sign"
            except Exception as e:  # noqa: BLE001
                db.rollback()
                raise HTTPException(400, str(e)) from e
    if agent.status == "published" and diff:
        if agent.owner_mode == "platform":
            if agent.ens_tx_hash and not agent.ens_tx_hash.startswith("0xmock"):
                ens_update_job(db, agent, diff)
                out["ens"] = "queued"
            else:
                out["ens"] = "mock"
        else:
            name = f"{agent.label}.{agent.parent_ens_name}"
            rep = {k: v for k, v in diff.items() if k in ens.REPUTATION_KEYS}
            prof = {k: v for k, v in diff.items() if k not in ens.REPUTATION_KEYS}
            if rep:
                ens_update_job(db, agent, rep)
            if not get_settings().sepolia_rpc_url or not agent_on_ens(agent):
                out["ens"], out["txs"] = "mock", []
            elif prof:
                try:
                    out["txs"] = ens.records_calldata_for(name=name, texts=prof)
                    out["ens"] = "sign"
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    raise HTTPException(400, str(e)) from e
            else:
                out["ens"] = "queued"
    db.commit()
    db.refresh(agent)
    out["agent"] = AgentOut.model_validate(agent)
    return out


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    out = AgentDetailOut.model_validate(agent)
    if agent.ens_name and agent_on_ens(agent):
        out.ens_reputation_name = ens.reputation_name_of(agent.ens_name)
        subs = [f"{x['role']}.{agent.ens_name}" for x in agent_subagents(agent)]
        got = ens.read_texts_many([(agent.ens_name, ens.PROFILE_KEYS), (out.ens_reputation_name, ens.REPUTATION_KEYS), *[(n, ens.SUBAGENT_KEYS) for n in subs]])
        out.ens_records = got[agent.ens_name]
        out.ens_reputation_records = got[out.ens_reputation_name]
        out.ens_subagents = {n: got[n] for n in subs}
        out.ens_roles = ens.agent_roles(agent.ens_name, agent.label)
    elif agent.ens_name:
        out.ens_records = ens.read_texts(agent.ens_name)
    return out


@router.get("/{agent_id}/reviews", response_model=list[ReviewOut])
def agent_reviews(agent_id: str, db: Session = Depends(get_db)):
    return db.query(Review).filter(Review.target_type == "agent", Review.target_id == agent_id).order_by(Review.created_at.desc()).all()


@router.get("/{agent_id}/earnings", response_model=AgentEarningsOut)
def earnings(agent_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """D3 / API-18: Creator の収益。この Agent が受けた案件の PM 管理費の工程（cases.PM_FEE_TITLE。計画側の role=pm タスクは含めない）を
    Escrow の投影から集計する。received = 実際に受取アドレスへ渡った額: paid は工程額、resolved は resolve ジョブの pay_amount（返金なら 0）、
    funded / submitted / disputed は預託中で 0。金額の正本は Escrow（Etherscan の tx）で、ここは DB の投影。Creator 本人だけが見られる。"""
    from .cases import PM_FEE_TITLE

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404)
    if agent.creator_id != user.id:
        raise HTTPException(403, "Only the Creator can view this")
    rows: list[EarningRowOut] = []
    paid = pending = resolved_total = 0
    q = (db.query(Task, Case).join(Case, Task.case_id == Case.id).filter(Case.agent_id == agent.id, Task.role == "pm", Task.title == PM_FEE_TITLE)
         .filter(Task.chain_status.in_(["funded", "submitted", "paid", "disputed", "resolved"])).order_by(Case.created_at.desc()))
    pairs = q.all()
    # resolved の受取額は resolve ジョブの payload（pay_amount）から。返金なら 0
    resolved_ids = [t.id for t, _ in pairs if t.chain_status == "resolved"]
    pay_by_task: dict[str, int] = {}
    if resolved_ids:
        for j in db.query(ChainJob).filter(ChainJob.kind == "resolve", ChainJob.payload["task_db_id"].as_string().in_(resolved_ids)).all():
            pay_by_task[j.payload["task_db_id"]] = int(j.payload.get("pay_amount") or 0)
    for t, c in pairs:
        amt = int(t.estimated_cost or 0)
        if t.chain_status == "paid":
            received = amt
            paid += amt
        elif t.chain_status == "resolved":
            received = pay_by_task.get(t.id, 0)
            resolved_total += received
        else:
            received = 0
            pending += amt
        rows.append(EarningRowOut(case_id=c.id, case_title=c.title, case_status=c.status, task_id=t.id, task_title=t.title, amount=str(amt), received=str(received),
                                  chain_status=t.chain_status, payee=t.payee, tx_hash=t.chain_tx_hash, at=t.completed_at or t.updated_at, budget=str(int(c.budget or 0))))
    return AgentEarningsOut(agent_id=agent.id, agent_name=agent.name, payout_address=agent.payout_address, fee_bps=agent.fee_bps,
                            paid_total=str(paid), pending_total=str(pending), resolved_total=str(resolved_total), cases=len(rows), rows=rows)
