"""AG-002 タスク分解エージェント（WP-011 / agent-definitions AG-002・agent-orchestration 9-2・9-4、context-templates AG-002）。
依頼文（cases.title + description）と policy の工程から、タスクの一覧（seq・phase・title）を作る。
- ツールを持たない（GRD-001。tools.ALLOWED["AG-002"] は空）。保存は AG-001 が TOOL-004 で行う（tool_plan.py）
- 予算額・候補・他の案件をコンテキストに入れない（context.build_ag002）
- 出力は 9-2 で検証し（tool_plan.validate_plan）、違反項目だけを CTX-008 に入れて再試行する（PMT-014。CG-007）。最大 3 回
- 呼ぶ前に停止（GRD-007）を確かめる。反復・時間・コストの上限は llm.call_structured が確かめる（GRD-005・11 章）
失敗は理由と違反項目を添えて返す。HIL-005 へのつなぎは AG-001（WP-015）。
既存の gemini.plan_case と /cases の流れは変えない（並べて作る）。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Agent, Case
from . import control, context, llm, trace
from .limits import LimitHit
from .tool_plan import TaskPlan, phases_for_case, validate_plan

MAX_ATTEMPTS = 3  # 9-4: 違反項目を添えて最大 3 回（AG-002 の反復上限 3 回と同じ）

Reason = Literal["violations", "empty", "limit", "stopped", "llm_error", "unavailable"]


@dataclass
class DecomposeResult:
    ok: bool
    run_id: str
    plan: TaskPlan | None = None
    reason: Reason | None = None
    violations: list[str] = field(default_factory=list)  # 最後の試行で違反した項目（HIL-005 に渡す材料）
    limit_hit: LimitHit | None = None
    attempts: int = 0


def requirement_text(case: Case) -> str:
    """設計の projects.requirement_text = cases.title + cases.description（計画 3 章の対応表）"""
    return "\n\n".join(x for x in (case.title, case.description) if x)


def default_mock(phases: list[dict]) -> Callable[[], dict]:
    """GEMINI_API_KEY が無いときの決定的な応答: 工程ごとに 1 タスク。"""
    return lambda: {"tasks": [{"seq": i, "phase": p["key"], "title": p["title"]} for i, p in enumerate(phases, 1)]}


def decompose(db: Session, *, case_id: str, parent_run_id: str | None = None,
              mock: Callable[[], str | dict] | None = None) -> DecomposeResult:
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case not found: {case_id}")
    phases = phases_for_case(case, db.get(Agent, case.agent_id))
    text = requirement_text(case)
    run = trace.start_run(db, "AG-002", mode="decompose", case_id=case_id, parent_run_id=parent_run_id, input_text=text)
    mock = mock or default_mock(phases)
    violations: list[str] = []

    def finish(result: DecomposeResult, status: str) -> DecomposeResult:
        detail = None if result.ok else f"{result.reason}: " + " / ".join(result.violations or ([result.limit_hit.detail] if result.limit_hit else []))
        trace.finish_run(db, run, status, error=detail)
        return result

    for attempt in range(1, MAX_ATTEMPTS + 1):
        stop = control.state_for_run(db, run)  # GRD-007: 止まっていれば次の呼び出しをしない
        if stop.stopped:
            return finish(DecomposeResult(False, run.id, reason="stopped", violations=violations, attempts=attempt - 1), "stopped")
        ctx = context.build_ag002(requirement_text=text, phases=phases, max_tasks=get_settings().agent_max_tasks_per_case,
                                  schema=TaskPlan, violations=violations)
        r = llm.call_structured(db=db, run=run, agent_id="AG-002", system=ctx.system, contents=ctx.contents, schema=TaskPlan, mock=mock)
        if r.failure == "limit":  # 上限到達の呼び出しは記録しない（LLM を呼んでいない）
            status = "stopped" if r.limit_hit and r.limit_hit.kind.startswith("cost") else "failed"
            return finish(DecomposeResult(False, run.id, reason="limit", violations=violations, limit_hit=r.limit_hit, attempts=attempt - 1), status)
        trace.record_llm(db, run, r, ctx.truncations)
        if r.failure in ("timeout", "error", "unavailable"):
            reason: Reason = "unavailable" if r.failure == "unavailable" else "llm_error"
            return finish(DecomposeResult(False, run.id, reason=reason, violations=[f"{r.failure}: {r.detail}"], attempts=attempt), "failed")
        if r.failure in ("parse", "schema"):  # CG-005: スキーマに合わない出力は受け取らない
            violations = [f"Output does not match the expected format ({r.failure}): {r.detail}"]
            continue
        if not r.output.tasks:  # PMT-002・010: 判断できないときは空の一覧を返す約束。推測で増やさせず、再試行しない
            return finish(DecomposeResult(False, run.id, reason="empty", violations=["No tasks (could not be determined from the request)"],
                                          attempts=attempt), "failed")
        violations = validate_plan(case_id, r.output, phases)  # 9-2（決定的なコード）
        if not violations:
            return finish(DecomposeResult(True, run.id, plan=r.output, attempts=attempt), "done")
    # 9-4: 上限に達したら AG-001 へ失敗を返す（HIL-005 は WP-015）
    return finish(DecomposeResult(False, run.id, reason="violations", violations=violations, attempts=MAX_ATTEMPTS), "failed")
