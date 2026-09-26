"""TOOL-008 request_requester_reconfirmation（可逆・冪等。WP-015 / agent-orchestration 6-2・12-3、HIL-005・GRD-004）。
発注者へ条件（依頼文・予算）の再確認を求める。設計の projects.status = 'draft' は、実装では cases.status = 'planning_failed'
（計画 3 章の対応表）。理由と違反項目を短く要約して cases.error に残す（発注者の画面に出る。既存の replan で計画し直せる）。
- 冪等: 案件ごとに開いている依頼は 1 件。同じ実行から何度呼んでも 1 回と数える
- GRD-004: 1 案件あたりの依頼の回数の上限（limits.check_reconfirm。既定 3 回）。超えたら依頼せずに案件を止める（control.stop）
呼べるのは AG-001 だけ（GRD-001）。理由と違反項目は実行基盤が手元の検証結果から渡す（モデルの出力をそのまま載せない）。"""

import logging

from sqlalchemy import func

from ..models import AgentRun, AgentToolCall, Case
from . import control, limits
from .tools import ToolContext, ToolError, register
from .trace import redact

log = logging.getLogger(__name__)

MAX_ERROR = 1000
REASON_LABEL = {
    "violations": "計画の検証に通りませんでした", "empty": "依頼文からタスクを判断できませんでした",
    "no_candidates": "担当の候補が見つかりませんでした", "no_plan": "タスク計画がありません",
    "limit": "処理の上限に達しました", "llm_error": "AI の呼び出しに失敗しました", "unavailable": "AI を利用できません",
    "search_error": "候補の検索に失敗しました", "orchestrator": "手順の指定が受理されませんでした", "tool_error": "保存に失敗しました",
}


def requested_count(ctx: ToolContext, case_id: str) -> int:
    """これまでに依頼した回数（TOOL-008 が成功した AG-001 の実行の数）。同じ実行の中の重複は 1 回と数える。"""
    q = (ctx.db.query(func.count(func.distinct(AgentToolCall.run_id))).join(AgentRun, AgentRun.id == AgentToolCall.run_id)
         .filter(AgentToolCall.tool_id == "TOOL-008", AgentToolCall.ok.is_(True), AgentRun.case_id == case_id))
    return int(q.scalar() or 0)


def summary(reason: str, violations: list[str]) -> str:
    text = f"再確認のお願い（{REASON_LABEL.get(reason, reason)}）"
    if violations:
        text += ": " + " / ".join(violations)
    return redact(text)[:MAX_ERROR]


@register("TOOL-008")
def request_requester_reconfirmation(ctx: ToolContext, *, case_id: str, reason: str, violations: list[str]) -> dict:
    if ctx.run.case_id != case_id:
        raise ToolError("この実行に結び付いた案件以外には依頼できません")
    case = ctx.db.get(Case, case_id)
    if case is None:
        raise ToolError("案件がありません")
    if case.status == "planning_failed":  # 冪等: 開いている依頼がある
        return {"requested": False, "already_open": True, "case_stopped": False}
    n = requested_count(ctx, case_id)
    hit = limits.check_reconfirm(case_id, n)  # GRD-004
    if hit is not None:
        control.stop(ctx.db, case_id=case_id, reason=f"GRD-004: 再確認の依頼が上限（{hit.limit:g} 回）に達しました", operator="AG-001")
        case.status, case.error = "planning_failed", redact(f"再確認の依頼が上限（{hit.limit:g} 回）に達したため、案件を止めました")[:MAX_ERROR]
        ctx.db.commit()
        log.warning("GRD-004: 再確認の依頼の上限に達したため案件を止めました（case:%s）", case_id)
        return {"requested": False, "already_open": False, "case_stopped": True}
    case.status, case.error = "planning_failed", summary(reason, violations)
    ctx.db.commit()
    return {"requested": True, "already_open": False, "case_stopped": False, "count": n + 1}
