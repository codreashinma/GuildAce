"""TOOL-005 save_team_proposal（可逆・冪等）と GRD-002（WP-014 / agent-orchestration 6-3・9-2・8 章）。
- AG-003 の出力は、タスクごとの担当の ENS 名と金額だけ（TeamProposal）。担当の種類（human / ai_agent）は、
  モデルに決めさせず、ENS 名から DB の索引（agents / members）でコードが決める（2026-09-26 ユーザー回答。6-3 からの逸脱）
- 保存の形は 6-3 の items（task_seq・assignee_kind・assignee_user_id・assignee_ens_name・amount）。人員にもユーザー ID が
  無いため、assignee_user_id は常に null で、担当は assignee_ens_name で持つ
- 9-2 の検証: 全タスクに担当が 1 つ、担当が候補（TOOL-002 の戻り値）の中にある、金額が 0 以上の整数の文字列
- GRD-002: sum(amount) <= 予算 を決定的なコードで検証し、超過なら保存しない。予算は既存の plan_case と同じく手数料を除いた額
TOOL-005 を呼べるのは AG-001 だけ（GRD-001）。保存の前に、同じ検証を DB から読み直した値でもう一度行う。"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..models import Agent, Case, Member
from . import trace
from .tool_search import search_candidates
from .tools import ToolContext, ToolError, register

_AMOUNT = re.compile(r"^[0-9]+$")  # 小数・負数・桁区切り・指数表記を受け付けない（PMT-007）


class TeamItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_seq: int
    assignee_ens_name: str
    amount: str


class TeamProposal(BaseModel):
    """AG-003 の出力（モデルが返す形）"""
    model_config = ConfigDict(extra="forbid")
    items: list[TeamItem]


class SavedItem(BaseModel):
    """6-3 save_team_proposal の items の 1 件（保存する形）"""
    task_seq: int
    assignee_kind: Literal["human", "ai_agent"]
    assignee_user_id: str | None
    assignee_ens_name: str
    amount: str


def usable_budget(case: Case, agent: Agent) -> int:
    """タスクに割り当てられる予算 = 案件の予算から PM Agent の手数料を除いた額（services/gemini.py の plan_case と同じ計算）"""
    return int(case.budget) * (10_000 - agent.fee_bps) // 10_000


def assignee_kind(db: Session, ens_name: str) -> Literal["human", "ai_agent"] | None:
    """ENS 名から担当の種類を決める（TOOL-002 の索引と同じ表）。どちらにも無ければ None。"""
    if db.query(Agent.id).filter(Agent.ens_name == ens_name).first():
        return "ai_agent"
    if db.query(Member.id).filter(Member.ens_name == ens_name).first():
        return "human"
    return None


def validate_proposal(proposal: TeamProposal, task_seqs: list[int], candidate_names: list[str], budget: int) -> tuple[list[str], int]:
    """9-2 と GRD-002。(違反項目, 超過額) を返す。違反項目にはモデルの出力値を入れない（CG-007）。超過額は数値（PMT-015）。"""
    out: list[str] = []
    seqs = [i.task_seq for i in proposal.items]
    missing = [s for s in task_seqs if s not in seqs]
    dup = sorted({s for s in seqs if seqs.count(s) > 1})
    unknown = [n for n, s in enumerate(seqs, 1) if s not in task_seqs]
    if missing:
        out.append(f"担当の無いタスクがあります（連番 {', '.join(map(str, missing))}）")
    if dup:
        out.append(f"担当が 2 つ以上あるタスクがあります（連番 {', '.join(map(str, dup))}）")
    if unknown:
        out.append(f"タスクの一覧に無い連番を指している項目があります（{', '.join(f'{n} 件目' for n in unknown)}）")
    names = set(candidate_names)
    outside = [n for n, i in enumerate(proposal.items, 1) if i.assignee_ens_name not in names]
    if outside:
        out.append(f"担当が候補の一覧にありません（{', '.join(f'{n} 件目' for n in outside)}）")
    bad_amount = [n for n, i in enumerate(proposal.items, 1) if not _AMOUNT.match(i.amount)]
    if bad_amount:
        out.append(f"金額が 0 以上の整数の文字列ではありません（{', '.join(f'{n} 件目' for n in bad_amount)}）")
    excess = 0
    if not bad_amount:
        total = sum(int(i.amount) for i in proposal.items)
        if total > budget:  # GRD-002
            excess = total - budget
            out.append(f"金額の合計が予算を超えています（超過額 {excess}）")
    return out, excess


def to_saved(db: Session, proposal: TeamProposal) -> list[dict]:
    items = []
    for i in proposal.items:
        kind = assignee_kind(db, i.assignee_ens_name)
        if kind is None:
            raise ToolError("担当の ENS 名が索引にありません")
        items.append(SavedItem(task_seq=i.task_seq, assignee_kind=kind, assignee_user_id=None,
                               assignee_ens_name=i.assignee_ens_name, amount=i.amount).model_dump())
    return items


def latest_task_seqs(db: Session, case_id: str) -> list[int]:
    """保存済みのタスク計画（TOOL-004）の最新版の連番。無ければ ToolError。"""
    plan = trace.latest_output(db, "task_plan", case_id)
    if plan is None:
        raise ToolError("タスク計画がまだ保存されていません")
    return [t["seq"] for t in plan.payload["tasks"]]


@register("TOOL-005")
def save_team_proposal(ctx: ToolContext, *, case_id: str, revision: int, items: list[dict]) -> dict:
    if ctx.run.case_id != case_id:
        raise ToolError("この実行に結び付いた案件以外には保存できません")
    case = ctx.db.get(Case, case_id)
    if case is None:
        raise ToolError("案件がありません")
    if revision < 1:
        raise ToolError("版番号は 1 以上にしてください")
    try:
        proposal = TeamProposal.model_validate({"items": items})  # AG-003 の出力の items をそのまま受け取る
    except ValueError as e:
        raise ToolError(f"チーム案の形が合いません: {e}") from e
    budget = usable_budget(case, ctx.db.get(Agent, case.agent_id))
    names = [c.ens_name for c in search_candidates(ctx.db, case_id).candidates]
    violations, _ = validate_proposal(proposal, latest_task_seqs(ctx.db, case_id), names, budget)
    if violations:  # 9-2・GRD-002: 検証に通らない案（予算超過を含む）は保存しない
        raise ToolError("チーム案の検証に失敗しました: " + " / ".join(violations))
    saved = to_saved(ctx.db, proposal)
    trace.save_output(ctx.db, "team_proposal", case_id, revision, {"items": saved}, ctx.run)
    return {"case_id": case_id, "revision": revision, "item_count": len(saved), "total": str(sum(int(i["amount"]) for i in saved))}
