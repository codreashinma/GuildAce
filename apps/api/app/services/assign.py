"""PM Agent による Human Task の指名（F10）。"""

import logging

from sqlalchemy.orm import Session

from ..models import Company, HumanTask, Member
from . import gemini

log = logging.getLogger(__name__)


def candidates_for(db: Session, ht: HumanTask) -> list[Member]:
    declined = set(ht.declined_member_ids or [])
    client_wallet = ht.case.client.wallet_address
    q = db.query(Member).join(Company).filter(Member.available.is_(True))
    return [m for m in q.all() if m.id not in declined and m.wallet_address.lower() != client_wallet]


def assign(db: Session, ht: HumanTask) -> None:
    """候補から 1 名を指名する。候補が無ければ公開募集（open）。"""
    cands = candidates_for(db, ht)
    case = ht.case
    if not cands:
        ht.status, ht.assignee_member_id, ht.assignment_reason = "open", None, "指名できる人員がいないため公開募集"
        db.commit()
        return
    payload = [{"ens_name": m.ens_name, "company": m.company.name, "role": m.role, "skills": m.skills, "location": m.location,
                "rating": float(m.rating_avg), "completed": m.completed_count} for m in cands]
    try:
        a = gemini.assign_human_task(agent_name=case.agent.name, agent_rules=case.agent.rules, task_title=ht.title, task_description=ht.description, candidates=payload)
    except Exception as e:  # noqa: BLE001
        log.exception("assignment failed")
        a = None
        ht.assignment_reason = f"指名に失敗したため公開募集（{e}）"
    if a is None:
        ht.status, ht.assignee_member_id = "open", None
        db.commit()
        return
    chosen = next((m for m in cands if m.ens_name == a.ens_name), cands[0])
    ht.status, ht.assignee_member_id, ht.assignment_reason = "assigned", chosen.id, a.reason
    db.commit()
