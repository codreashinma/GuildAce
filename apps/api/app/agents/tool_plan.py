"""TOOL-004 save_task_plan（可逆・冪等。WP-011 / agent-orchestration 6-2・9-2）。
タスク計画（AG-002 の出力）を agent_outputs に版付きで保存する。冪等キーは 案件 ID + 版番号（同じ版は上書き）。
呼べるのは AG-001 だけ（GRD-001。tools.ALLOWED）。AG-002 はツールを持たない。
保存の前に 9-2 の検証（件数 1〜GRD-003・seq が 1 からの連番・phase が工程キーに存在）をもう一度行い、通らなければ保存しない。
出力の形（TaskPlan）は AG-002 の出力スキーマと同じ（context-templates の AG-002「出力スキーマ」）。"""

from pydantic import BaseModel, ConfigDict, Field

from ..models import Agent, Case
from . import limits, policy, trace
from .tools import ToolContext, ToolError, register


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int
    phase: str
    title: str = Field(min_length=1)


class TaskPlan(BaseModel):
    """AG-002 の出力 = TOOL-004 の入力。金額と担当者は持たない（AG-002 の「担わないこと」）"""
    model_config = ConfigDict(extra="forbid")
    tasks: list[PlannedTask]


def phases_for_case(case: Case, agent: Agent) -> list[dict]:
    """案件の PM Agent の工程（policy.workflow.phases。無ければ既定の policy。DEC-002）"""
    return policy.effective(agent.policy, agent.category)["workflow"]["phases"]


def validate_plan(case_id: str, plan: TaskPlan, phases: list[dict]) -> list[str]:
    """9-2 の検証。違反項目の一覧を返す（空なら合格）。モデルの出力値は入れず、どこが違反かだけを書く（CG-007）。"""
    out: list[str] = []
    n = len(plan.tasks)
    if n < 1:
        out.append("There are no tasks")
    hit = limits.check_task_count(case_id, n)  # GRD-003
    if hit is not None:
        out.append(f"Too many tasks ({n}, limit {hit.limit:g})")
    seqs = [t.seq for t in plan.tasks]
    if seqs != list(range(1, n + 1)):
        out.append(f"Sequence numbers are not consecutive from 1 to {n} ({sum(1 for i, s in enumerate(seqs, 1) if s != i)} of {n} do not match their position)")
    keys = {p["key"] for p in phases}
    bad = [i for i, t in enumerate(plan.tasks, 1) if t.phase not in keys]
    if bad:
        out.append(f"Step keys not in the step list are used (items {', '.join(str(i) for i in bad[:10])})")
    return out


@register("TOOL-004")
def save_task_plan(ctx: ToolContext, *, case_id: str, revision: int, tasks: list[dict]) -> dict:
    if ctx.run.case_id != case_id:
        raise ToolError("Can only save to the case linked to this run")
    case = ctx.db.get(Case, case_id)
    if case is None:
        raise ToolError("Case not found")
    if revision < 1:
        raise ToolError("The revision number must be 1 or greater")
    try:
        plan = TaskPlan.model_validate({"tasks": tasks})
    except ValueError as e:
        raise ToolError(f"The task plan has an invalid format: {e}") from e
    violations = validate_plan(case_id, plan, phases_for_case(case, ctx.db.get(Agent, case.agent_id)))
    if violations:  # 9-2: 検証に通らない出力は保存しない
        raise ToolError("The task plan failed validation: " + " / ".join(violations))
    trace.save_output(ctx.db, "task_plan", case_id, revision, plan.model_dump(), ctx.run)
    return {"case_id": case_id, "revision": revision, "task_count": len(plan.tasks)}
