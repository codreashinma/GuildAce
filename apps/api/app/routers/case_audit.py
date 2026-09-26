"""監査ビュー（G2 / API-30 / NFR-010）。案件ごとのオンチェーン tx（openCase / fund / submit / approve / pay / dispute / resolve）と
ENS への発行を時系列に並べ、関わったアドレス（発注者・承認者・支払先・Jury）をプラットフォームが発行した ENS 名で表示する。
正本はコントラクトと ENS。ここでは DB が保持する tx hash と chain_jobs（ADR-006）を読み取るだけで、書き込みは行わない。"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, ChainJob, Dispute, JuryVote, Task
from .cases import _load
from .ens import _reverse_one

router = APIRouter(prefix="/cases", tags=["cases"])

KIND_LABEL = {
    "openCase": "案件を開く（承認者と必要承認数を固定）", "fund_task": "工程の預託", "submit": "成果物の提出", "approve": "承認（World 確認 + EIP-712）",
    "pay": "自動支払い（必要承認数に到達）", "dispute": "差し戻し（保留）", "resolve": "Jury 裁定による解放", "ens_publish": "Agent を ENS に公開", "ens_project": "案件の project subname を発行",
}


class AuditActor(BaseModel):
    address: str
    name: str | None = None
    source: str | None = None
    verified: bool = False
    roles: list[str] = []


class AuditEvent(BaseModel):
    seq: int
    kind: str
    label: str
    task_id: str | None = None
    task_title: str | None = None
    actor: str | None = None  # 送信者 / 署名者のアドレス。worker（サーバー鍵）が中継した tx は role で示す
    actor_role: str  # client | approver | worker | project-key | owner-key | creator | jury
    tx_hash: str | None = None
    mock: bool = False
    status: str  # done | queued | running | retry | failed | recorded
    at: datetime | None = None
    detail: dict[str, Any] = {}


class CaseAuditOut(BaseModel):
    case_id: str
    title: str
    status: str
    escrow_case_id: str
    approvers: list[str]
    threshold: int
    project_ens_name: str | None
    agent_ens_name: str | None
    events: list[AuditEvent]
    actors: dict[str, AuditActor]
    counts: dict[str, int]


def _mock(tx: str | None) -> bool:
    return bool(tx) and tx.startswith("0xmock")


@router.get("/{case_id}/audit", response_model=CaseAuditOut)
def case_audit(case_id: str, db: Session = Depends(get_db)):
    """案件の tx 一覧と、承認者・支払先・Jury の ENS 名（逆引き）。認証不要（第三者の監査向け）。署名や nullifier は返さない。"""
    case = _load(db, case_id)
    tasks: dict[str, Task] = {t.id: t for t in case.tasks}
    actors: dict[str, AuditActor] = {}

    def actor(addr: str | None, role: str) -> str | None:
        if not addr:
            return None
        a = addr.lower()
        if a not in actors:
            actors[a] = AuditActor(**_reverse_one(db, a))
        if role not in actors[a].roles:
            actors[a].roles.append(role)
        return a

    actor(case.client.wallet_address, "client")
    for ap in case.approvers or []:
        actor(ap, "approver")

    events: list[AuditEvent] = []

    def add(kind: str, *, task: Task | None = None, actor_addr: str | None = None, role: str, tx: str | None, status: str, at: datetime | None, **detail: Any) -> None:
        events.append(AuditEvent(seq=0, kind=kind, label=KIND_LABEL.get(kind, kind), task_id=task.id if task else None, task_title=task.title if task else None,
                                 actor=actor(actor_addr, role), actor_role=role, tx_hash=tx, mock=_mock(tx), status=status, at=at, detail={k: v for k, v in detail.items() if v is not None}))

    # --- ENS: Agent の公開（案件より前。名前空間の出自を示す）
    ag: Agent = case.agent
    if ag.ens_name:
        add("ens_publish", actor_addr=ag.creator.wallet_address if ag.owner_mode == "creator" else None, role="creator" if ag.owner_mode == "creator" else "owner-key",
            tx=ag.ens_tx_hash, status="recorded", at=ag.updated_at, ens_name=ag.ens_name, owner_mode=ag.owner_mode)

    # --- openCase（発注者の署名。API は tx を検証してから記録する）
    if case.open_tx_hash:
        add("openCase", actor_addr=case.client.wallet_address, role="client", tx=case.open_tx_hash, status="recorded", at=None, approvers=case.approvers, threshold=case.threshold)

    # --- worker のジョブ（fund / submit / approve / dispute / resolve / ens_project）
    jobs = (
        db.query(ChainJob)
        .filter(ChainJob.kind.in_(["fund_task", "submit", "approve", "dispute", "resolve", "ens_project"]))
        .filter((ChainJob.payload["task_db_id"].as_string().in_(list(tasks))) | (ChainJob.idempotency_key == f"ens_project:{case.id}"))
        .order_by(ChainJob.created_at)
        .all()
    )
    approve_seen: dict[str, int] = {}
    for j in jobs:
        p = j.payload or {}
        t = tasks.get(p.get("task_db_id", ""))
        when = j.finished_at or j.created_at
        if j.kind == "fund_task":
            add("fund_task", task=t, role="worker", tx=j.tx_hash, status=j.status, at=when, amount=p.get("amount"), error=j.error)
        elif j.kind == "submit":
            add("submit", task=t, role="worker", tx=j.tx_hash, status=j.status, at=when, deliverable_hash=p.get("deliverable_hash"), payee=p.get("payee"), error=j.error)
            actor(p.get("payee"), "payee")
        elif j.kind == "approve":
            n = approve_seen.get(p.get("task_db_id", ""), 0) + 1
            approve_seen[p.get("task_db_id", "")] = n
            add("approve", task=t, actor_addr=p.get("approver"), role="approver", tx=j.tx_hash, status=j.status, at=when,
                deliverable_hash=p.get("deliverable_hash"), approval_count=n, threshold=p.get("threshold"), error=j.error)
            # 必要数に到達した approve で Escrow が支払う（同じ tx）
            if t is not None and t.chain_status == "paid" and n >= int(p.get("threshold") or case.threshold):
                add("pay", task=t, actor_addr=t.payee, role="payee", tx=j.tx_hash, status=j.status, at=when, payee=t.payee, amount=str(int(t.estimated_cost)))
        elif j.kind == "dispute":
            add("dispute", task=t, actor_addr=case.client.wallet_address, role="client", tx=j.tx_hash, status=j.status, at=when, error=j.error)
        elif j.kind == "resolve":
            add("resolve", task=t, role="worker", tx=j.tx_hash, status=j.status, at=when, pay_amount=p.get("pay_amount"), refund_amount=p.get("refund_amount"), error=j.error)
        elif j.kind == "ens_project":
            add("ens_project", role="project-key", tx=j.tx_hash, status=j.status, at=when, ens_name=case.project_ens_name, error=j.error)

    # --- Jury（tx は無いが、誰が裁定に関わったかを ENS 名で示す）
    for d in db.query(Dispute).filter(Dispute.case_id == case.id).order_by(Dispute.created_at).all():
        for v in db.query(JuryVote).filter(JuryVote.dispute_id == d.id).all():
            actor(v.voter.wallet_address, "jury")
        events.append(AuditEvent(seq=0, kind="jury", label=f"Jury 裁定（{len(d.votes)} 票 / 必要 {d.required_votes}）", actor=None, actor_role="jury", tx_hash=None, mock=False,
                                 status=d.status, at=d.updated_at, detail={"dispute_id": d.id, "outcome": d.outcome, "voters": [v.voter.wallet_address.lower() for v in d.votes]}))

    # 並び: Agent の公開 → openCase（tx の時刻は DB に無いが、worker ジョブはすべて openCase 後に投入される）→ 時刻順
    order = {"ens_publish": 0, "openCase": 1}
    events.sort(key=lambda e: (order.get(e.kind, 2), (e.at.timestamp() if e.at else 0.0)))
    for i, e in enumerate(events, 1):
        e.seq = i

    counts = {"events": len(events), "onchain": sum(1 for e in events if e.tx_hash and not e.mock), "mock": sum(1 for e in events if e.tx_hash and e.mock),
              "failed": sum(1 for e in events if e.status == "failed"), "named_actors": sum(1 for a in actors.values() if a.name)}
    return CaseAuditOut(case_id=case.id, title=case.title, status=case.status, escrow_case_id=case.escrow_case_id, approvers=[a.lower() for a in (case.approvers or [])],
                        threshold=case.threshold, project_ens_name=case.project_ens_name, agent_ens_name=ag.ens_name, events=events, actors=actors, counts=counts)
