"""TOOL-002 search_agents_by_ens（参照のみ。WP-013 / agent-orchestration 6-3・CG-008・context-templates AG-003「参照データの選び方」）。
AG-003 に渡す候補を返す。候補の出どころは DEC-009 (a):
- 索引は DB。公開済みで ENS に実在する Agent（routers.agents.agent_on_ens）と、ENS に書き込み済みで受付中の人員（members）
- 属性は ENS の構造化された text record だけを、キーを指定して読む（read_texts）。description などの自由文は読まない（CG-008）
- reputation_score は DB の rating_avg（DEC-009）。評価が無ければ null
並びは reputation_score 降順 → human_review_count 降順 → ens_name 昇順で固定（同点でも順序が決まる）。
上限（DEC-004。agent_max_candidates）を超えたら切り、truncated: true を返す。発注者自身（案件の client）は除く。"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Agent, Case, Company, Member, User
from ..routers.agents import agent_on_ens
from ..services import ens
from .tools import ToolContext, ToolError, register

AGENT_KEYS = ["codrea.agent.category"]  # 構造化された値だけ（description・url などは読まない）
PERSON_KEYS = ["codrea.person.role", "codrea.person.company"]
MAX_VALUE = 60  # ENS の値の長さの上限（構造化された値として扱える長さに切る）


class Candidate(BaseModel):
    """6-3 search_agents_by_ens の出力の 1 件"""
    ens_name: str
    domain: str
    creator_ens_name: str
    reputation_score: float | None
    human_review_count: int | None


class SearchResult(BaseModel):
    candidates: list[Candidate]
    truncated: bool


def _value(texts: dict[str, str], key: str) -> str:
    return (texts.get(key) or "").strip()[:MAX_VALUE]


def _agent_candidates(db: Session, client: User) -> list[Candidate]:
    s = get_settings()
    out = []
    for a in db.query(Agent).filter(Agent.status == "published", Agent.creator_id != client.id).all():
        if not (a.ens_name and agent_on_ens(a)):
            continue
        domain = _value(ens.read_texts(a.ens_name, AGENT_KEYS), "codrea.agent.category")
        if not domain:  # ENS で読めない名前は候補にしない
            continue
        out.append(Candidate(ens_name=a.ens_name, domain=domain, creator_ens_name=a.parent_ens_name or s.ens_parent_name,
                             reputation_score=float(a.rating_avg) if a.rating_count else None, human_review_count=int(a.rating_count)))
    return out


def _member_candidates(db: Session, client: User) -> list[Candidate]:
    out = []
    q = db.query(Member).join(Company).filter(Member.ens_status == "written", Member.available.is_(True))
    for m in q.all():
        if m.wallet_address.lower() == client.wallet_address.lower():
            continue
        texts = ens.read_texts(m.ens_name, PERSON_KEYS)
        domain, company = _value(texts, "codrea.person.role"), _value(texts, "codrea.person.company")
        if not domain:
            continue
        out.append(Candidate(ens_name=m.ens_name, domain=domain, creator_ens_name=company,
                             reputation_score=float(m.rating_avg) if m.completed_count else None, human_review_count=None))
    return out


def sort_key(c: Candidate) -> tuple:
    """reputation_score 降順 → human_review_count 降順 → ens_name 昇順。null はそれぞれの最後"""
    return (c.reputation_score is None, -(c.reputation_score or 0), c.human_review_count is None, -(c.human_review_count or 0), c.ens_name)


def search_candidates(db: Session, case_id: str) -> SearchResult:
    case = db.get(Case, case_id)
    if case is None:
        raise ToolError("案件がありません")
    client = db.get(User, case.client_id)
    found = sorted(_agent_candidates(db, client) + _member_candidates(db, client), key=sort_key)
    cap = get_settings().agent_max_candidates
    return SearchResult(candidates=found[:cap], truncated=len(found) > cap)


@register("TOOL-002")
def search_agents_by_ens(ctx: ToolContext, *, case_id: str) -> dict:
    if ctx.run.case_id != case_id:
        raise ToolError("この実行に結び付いた案件以外の候補は検索できません")
    return search_candidates(ctx.db, case_id).model_dump()
