"""マイページ（A4 / API-90）。ログイン中のウォレットに紐づくものをまとめて返す:
ENS 名（このプラットフォームが発行した名前。人員・Agent 受取・会社管理者）、World ID で人間確認した行為、所属会社、作成した Agent、
関わった案件、受取履歴（Escrow が自分のアドレスへ支払った工程）。nullifier や署名は返さない。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user
from ..db import get_db
from ..models import Agent, Case, Company, HumanTask, JuryVote, Member, Review, Task, User, WorldVerification
from .ens import _reverse_one

router = APIRouter(prefix="/me", tags=["me"])

ACTION_LABEL = {"request": "依頼開始", "approve": "工程の承認", "review": "レビュー投稿", "jury": "Jury 投票", "human-task": "Human Task 受注"}


class EnsNameOut(BaseModel):
    name: str
    kind: str  # person | agent-payout | company-admin | agent-creator
    verified: bool
    tx_hash: str | None = None
    link: str
    note: str | None = None


class WorldActionOut(BaseModel):
    action: str
    label: str
    count: int
    last_at: datetime | None = None


class CompanyBrief(BaseModel):
    id: str
    name: str
    ens_name: str
    ens_verified: bool
    relation: str  # admin | member
    member_name: str | None = None
    member_ens: str | None = None
    available: bool | None = None


class AgentBrief(BaseModel):
    id: str
    name: str
    status: str
    ens_name: str | None
    owner_mode: str
    rating_avg: float
    rating_count: int
    completed_count: int


class EarningOut(BaseModel):
    case_id: str
    case_title: str
    task_id: str
    task_title: str
    role: str  # pm | human | ai
    amount: str
    chain_status: str
    tx_hash: str | None
    at: datetime | None


class MeSummaryOut(BaseModel):
    user: dict
    primary_ens: EnsNameOut | None
    ens_names: list[EnsNameOut]
    world_actions: list[WorldActionOut]
    companies: list[CompanyBrief]
    agents: list[AgentBrief]
    cases: dict[str, int]  # as_client / as_approver / as_worker / as_jury
    earnings: list[EarningOut]
    earnings_total: str
    reviews_received: dict


@router.get("/summary", response_model=MeSummaryOut)
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    me = user.wallet_address.lower()

    # --- ENS 名（発行順）
    names: list[EnsNameOut] = []
    for m in db.query(Member).filter(Member.wallet_address == me).order_by(Member.created_at).all():
        names.append(EnsNameOut(name=m.ens_name, kind="person", verified=m.ens_status == "written", tx_hash=m.ens_tx_hash, link="/companies", note=f"{m.company.name} の人員"))
    for a in db.query(Agent).filter(Agent.payout_address == me, Agent.ens_name.isnot(None)).order_by(Agent.created_at).all():
        names.append(EnsNameOut(name=a.ens_name, kind="agent-payout", verified=bool(a.ens_tx_hash and not a.ens_tx_hash.startswith("0xmock")), tx_hash=a.ens_tx_hash, link=f"/agents/{a.id}", note="受取アドレス = 自分"))
    for c in db.query(Company).filter(Company.admin_id == user.id).order_by(Company.created_at).all():
        names.append(EnsNameOut(name=c.ens_name, kind="company-admin", verified=c.ens_verified, tx_hash=None, link="/companies", note="会社の管理者（名前の所有者）"))
    primary_raw = _reverse_one(db, me)
    primary = next((n for n in names if n.name == primary_raw["name"]), None) if primary_raw["name"] else None

    # --- World ID で人間確認した行為（nullifier は出さない）
    world: dict[str, WorldActionOut] = {}
    for v in db.query(WorldVerification).filter(WorldVerification.user_id == user.id).order_by(WorldVerification.created_at).all():
        w = world.setdefault(v.action, WorldActionOut(action=v.action, label=ACTION_LABEL.get(v.action, v.action), count=0))
        w.count += 1
        w.last_at = v.created_at

    # --- 所属会社
    companies: list[CompanyBrief] = [CompanyBrief(id=c.id, name=c.name, ens_name=c.ens_name, ens_verified=c.ens_verified, relation="admin")
                                     for c in db.query(Company).filter(Company.admin_id == user.id).all()]
    for m in db.query(Member).options(selectinload(Member.company)).filter(Member.wallet_address == me).all():
        companies.append(CompanyBrief(id=m.company.id, name=m.company.name, ens_name=m.company.ens_name, ens_verified=m.company.ens_verified, relation="member",
                                      member_name=m.name, member_ens=m.ens_name, available=m.available))

    # --- 作成した Agent
    agents = [AgentBrief(id=a.id, name=a.name, status=a.status, ens_name=a.ens_name, owner_mode=a.owner_mode, rating_avg=float(a.rating_avg or 0), rating_count=a.rating_count, completed_count=a.completed_count)
              for a in db.query(Agent).filter(Agent.creator_id == user.id).order_by(Agent.created_at.desc()).all()]

    # --- 関わった案件
    as_client = db.query(Case).filter(Case.client_id == user.id).count()
    as_approver = sum(1 for c in db.query(Case).filter(Case.approvers.isnot(None)).all() if me in [x.lower() for x in (c.approvers or [])])
    as_worker = db.query(HumanTask).filter(HumanTask.worker_id == user.id).count()
    as_jury = db.query(JuryVote).filter(JuryVote.voter_id == user.id).count()

    # --- 受取履歴: Escrow が自分のアドレスへ支払った工程（paid）と、裁定で解放された工程（resolved）
    earnings: list[EarningOut] = []
    total = 0
    q = db.query(Task).options(selectinload(Task.case), selectinload(Task.human_task)).filter(Task.payee == me, Task.chain_status.in_(["paid", "resolved"])).order_by(Task.updated_at.desc())
    for t in q.all():
        role = "human" if t.type == "human" else ("pm" if "PM" in (t.title or "") or t.role in ("pm", "manager") else "ai")
        amt = int(t.estimated_cost or 0)
        if t.chain_status == "paid":
            total += amt
        earnings.append(EarningOut(case_id=t.case_id, case_title=t.case.title, task_id=t.id, task_title=t.title, role=role, amount=str(amt), chain_status=t.chain_status,
                                   tx_hash=t.chain_tx_hash, at=t.completed_at or t.updated_at))

    # --- 自分（人として）に付いたレビュー
    rs = db.query(Review).filter(Review.target_type == "user", Review.target_id == user.id).all()
    reviews_received = {"count": len(rs), "avg": round(sum(r.rating for r in rs) / len(rs), 1) if rs else None}

    return MeSummaryOut(
        user={"id": user.id, "wallet_address": user.wallet_address, "display_name": user.display_name, "created_at": user.created_at},
        primary_ens=primary, ens_names=names, world_actions=list(world.values()), companies=companies, agents=agents,
        cases={"as_client": as_client, "as_approver": as_approver, "as_worker": as_worker, "as_jury": as_jury},
        earnings=earnings, earnings_total=str(total), reviews_received=reviews_received,
    )
