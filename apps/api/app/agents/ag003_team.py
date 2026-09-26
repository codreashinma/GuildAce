"""AG-003 チーム編成エージェント（WP-014 / agent-definitions AG-003・agent-orchestration 9-2・9-4、context-templates AG-003）。
保存済みのタスク計画（TOOL-004 の最新版）と、TOOL-002 の候補と、予算から、タスクごとの担当と金額の案を作る。
- 予算は手数料を除いた額（tool_team.usable_budget。既存の plan_case と同じ）。CTX-005 に入る
- 候補は TOOL-002 だけから取る（tools.call_tool 経由。GRD-001・GRD-007 はそこで効く）。候補が 0 件ならモデルを呼ばない（捏造させない）
- 出力は 9-2 と GRD-002 で検証し（tool_team.validate_proposal）、違反項目と超過額（数値）だけを CTX-008 に入れて再試行する
  （PMT-015。CG-007）。最大 3 回
- 担当の種類は ENS 名からコードが決める（tool_team.assignee_kind）。保存は AG-001 が TOOL-005 で行う
失敗は理由と違反項目を添えて返す。HIL-005 へのつなぎは AG-001（WP-015）。
既存の gemini.plan_case と /cases の流れは変えない（並べて作る）。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from ..models import Agent, Case
from . import context, control, llm, policy, tools, trace
from .limits import LimitHit
from .tool_team import TeamProposal, usable_budget, validate_proposal

MAX_ATTEMPTS = 3  # 9-4: 予算超過のときは超過額を添えて最大 3 回

Reason = Literal["no_plan", "no_candidates", "search_error", "violations", "limit", "stopped", "llm_error", "unavailable"]


@dataclass
class TeamResult:
    ok: bool
    run_id: str | None
    proposal: TeamProposal | None = None
    reason: Reason | None = None
    violations: list[str] = field(default_factory=list)
    excess: int = 0  # 最後の試行の超過額（GRD-002。HIL-005 に渡す材料）
    limit_hit: LimitHit | None = None
    attempts: int = 0


def default_mock(tasks: list[dict], names: list[str], budget: int) -> Callable[[], dict]:
    """GEMINI_API_KEY が無いときの決定的な応答: 候補を順に割り当て、予算を等分する（合計は予算以内）。"""
    each = budget // max(len(tasks), 1)
    return lambda: {"items": [{"task_seq": t["seq"], "assignee_ens_name": names[i % len(names)], "amount": str(each)}
                              for i, t in enumerate(tasks)]}


def form_team(db: Session, *, case_id: str, parent_run_id: str | None = None,
              mock: Callable[[], str | dict] | None = None) -> TeamResult:
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError(f"案件がありません: {case_id}")
    plan = trace.latest_output(db, "task_plan", case_id)
    if plan is None:  # AG-002 の計画（TOOL-004 で保存）が先に要る
        return TeamResult(False, None, reason="no_plan", violations=["タスク計画がまだ保存されていません"])
    tasks = plan.payload["tasks"]
    agent = db.get(Agent, case.agent_id)
    budget = usable_budget(case, agent)
    human_roles = policy.effective(agent.policy, agent.category)["human_roles"]
    run = trace.start_run(db, "AG-003", mode="form_team", case_id=case_id, parent_run_id=parent_run_id,
                          input_text="\n".join(t["title"] for t in tasks))

    def finish(result: TeamResult, status: str) -> TeamResult:
        detail = None if result.ok else f"{result.reason}: " + " / ".join(result.violations or ([result.limit_hit.detail] if result.limit_hit else []))
        trace.finish_run(db, run, status, error=detail)
        return result

    got = tools.call_tool(db, run, "TOOL-002", case_id=case_id)
    if got.stopped:
        return finish(TeamResult(False, run.id, reason="stopped"), "stopped")
    if not got.ok:
        return finish(TeamResult(False, run.id, reason="search_error", violations=[got.error or ""]), "failed")
    candidates = got.value["candidates"]
    names = [c["ens_name"] for c in candidates]
    if not candidates:  # 候補が無ければ担当を作れない。モデルに推測させない（PMT-003）
        return finish(TeamResult(False, run.id, reason="no_candidates", violations=["候補が 0 件です"]), "failed")
    mock = mock or default_mock(tasks, names, budget)
    task_seqs = [t["seq"] for t in tasks]
    violations: list[str] = []
    excess = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if control.state_for_run(db, run).stopped:  # GRD-007
            return finish(TeamResult(False, run.id, reason="stopped", violations=violations, excess=excess, attempts=attempt - 1), "stopped")
        ctx = context.build_ag003(budget_amount=str(budget), human_roles=human_roles, tasks=tasks, candidates=candidates,
                                  schema=TeamProposal, violations=violations, excess_amount=str(excess))
        r = llm.call_structured(db=db, run=run, agent_id="AG-003", system=ctx.system, contents=ctx.contents, schema=TeamProposal, mock=mock)
        if r.failure == "limit":
            status = "stopped" if r.limit_hit and r.limit_hit.kind.startswith("cost") else "failed"
            return finish(TeamResult(False, run.id, reason="limit", violations=violations, excess=excess, limit_hit=r.limit_hit,
                                     attempts=attempt - 1), status)
        trace.record_llm(db, run, r, ctx.truncations)
        if r.failure in ("timeout", "error", "unavailable"):
            reason: Reason = "unavailable" if r.failure == "unavailable" else "llm_error"
            return finish(TeamResult(False, run.id, reason=reason, violations=[f"{r.failure}: {r.detail}"], attempts=attempt), "failed")
        if r.failure in ("parse", "schema"):  # CG-005
            violations, excess = [f"出力の形が合いません（{r.failure}）: {r.detail}"], 0
            continue
        violations, excess = validate_proposal(r.output, task_seqs, names, budget)  # 9-2・GRD-002（決定的なコード）
        if not violations:
            return finish(TeamResult(True, run.id, proposal=r.output, attempts=attempt), "done")
    # 9-4: 上限に達したら AG-001 へ失敗を返す（HIL-005 は WP-015）
    return finish(TeamResult(False, run.id, reason="violations", violations=violations, excess=excess, attempts=MAX_ATTEMPTS), "failed")
