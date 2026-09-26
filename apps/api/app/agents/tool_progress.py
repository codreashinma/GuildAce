"""TOOL-006 update_task_progress（可逆・冪等。WP-016 / agent-orchestration 6-2・FR-008）。
タスクの進捗から案件の状態を導き直す。判断はしない: 既存の状態の投影（routers.cases.after_chain_update。
タスクのオンチェーン投影が正本。ADR-001）をそのまま呼ぶだけで、エージェントから状態の値は受け取らない。
同じ入力で何度呼んでも結果は同じ（2 回目以降は変化なし）。呼べるのは AG-001 だけ（GRD-001）。"""

from ..models import Case, Task
from ..routers.cases import after_chain_update
from .tools import ToolContext, ToolError, register


@register("TOOL-006")
def update_task_progress(ctx: ToolContext, *, task_id: str) -> dict:
    task = ctx.db.get(Task, task_id)
    if task is None:
        raise ToolError("Task not found")
    if ctx.run.case_id != task.case_id:
        raise ToolError("Only tasks of the case linked to this run can be handled")
    before = ctx.db.get(Case, task.case_id).status
    after_chain_update(ctx.db, task.case_id)
    ctx.db.expire_all()
    after = ctx.db.get(Case, task.case_id).status
    return {"case_id": task.case_id, "task_id": task_id, "status": after, "changed": before != after}
