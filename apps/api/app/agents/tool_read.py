"""TOOL-001 read_project_context（参照のみ。WP-006）。
実行（run）に結び付いた案件 1 件だけを返す。返さないもの（agent-context 8 章・context-templates）:
ウォレットアドレス・支払先・承認者のアドレス・World の nullifier・成果物の本文・タスクごとの金額・他の案件。
設計の projects は実装の cases（計画 3 章の対応表）。"""

from ..models import Case, Dispute
from .tools import ToolContext, ToolError, register


def _allowed_case_id(ctx: ToolContext) -> str | None:
    """run が案件か紛争に結び付いていれば、その案件の ID。どちらでもなければ None（何も読ませない）。"""
    if ctx.run.case_id:
        return ctx.run.case_id
    if ctx.run.dispute_id:
        d = ctx.db.get(Dispute, ctx.run.dispute_id)
        return d.case_id if d else None
    return None


@register("TOOL-001")
def read_project_context(ctx: ToolContext, *, case_id: str) -> dict:
    allowed = _allowed_case_id(ctx)
    if allowed is None or case_id != allowed:
        raise ToolError("この実行に結び付いた案件以外は読めません")
    case = ctx.db.get(Case, case_id)
    if case is None:
        raise ToolError("案件が見つかりません")
    return {
        "case_id": case.id,
        "title": case.title,
        "description": case.description,
        "budget_amount": str(int(case.budget)),  # 整数の文字列（金額に浮動小数を使わない）
        "deadline": case.deadline,
        "status": case.status,
        "approver_count": len(case.approvers or []),
        "threshold": case.threshold,
        "agent": {"name": case.agent.name, "category": case.agent.category},
        "tasks": [
            {"seq": t.order_no + 1, "title": t.title, "type": t.type, "role": t.role, "status": t.status,
             "chain_status": t.chain_status, "has_deliverable": bool(t.deliverable)}
            for t in sorted(case.tasks, key=lambda t: t.order_no)
        ],
    }
