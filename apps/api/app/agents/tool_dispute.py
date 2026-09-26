"""TOOL-003 read_dispute_record（参照のみ）と TOOL-007 save_dispute_summary（可逆・冪等）（WP-012 / agent-orchestration 6-2・9-2）。
- TOOL-003 は AG-004 が呼ぶ。紛争の案件のタスクの記録を、構造化された値だけで返す（context-templates AG-004 の CTX-005:
  成果物のハッシュ・承認の有無・状態）。成果物の本文・タスク名・アドレス・承認者・nullifier は返さない（12-2・OQ-006）
- 参照 ID は "deliverable:<タスク ID>"（成果物のあるタスク）と "approval:<承認 ID>"。争点の evidence_refs はこの中から選ぶ
- TOOL-007 は AG-001 が呼ぶ。保存の前に 9-2 の検証をもう一度行い、通らなければ保存しない。冪等キーは 紛争 ID + 版番号
紛争は案件単位で、対象のタスクを 1 つに決める列が無い（disputes に task_id が無い）ため、案件のタスクすべての記録を返す。"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..models import Dispute, Task
from . import trace
from .tools import ToolContext, ToolError, register


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 結論（verdict など）のキーはスキーマ違反
    title: str = Field(min_length=1)
    requester_position: str
    provider_position: str
    evidence_refs: list[str]


class DisputeSummary(BaseModel):
    """AG-004 の出力 = TOOL-007 の入力。裁定（どちらが正しいか）の項目を持たない"""
    model_config = ConfigDict(extra="forbid")
    issues: list[Issue]


def dispute_record(db: Session, dispute_id: str) -> dict:
    """紛争の案件のタスクの記録（構造化された値だけ）と、参照できる ID の一覧。"""
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise ToolError("Dispute not found")
    tasks = db.query(Task).filter(Task.case_id == d.case_id).order_by(Task.order_no).all()
    records, refs = [], []
    for t in tasks:
        approvals = [f"approval:{a.id}" for a in t.approvals]
        deliverable = f"deliverable:{t.id}" if (t.deliverable_hash or t.deliverable) else None
        records.append({
            "task_ref": f"task:{t.id}", "seq": t.order_no + 1, "status": t.status, "chain_status": t.chain_status,
            "deliverable_ref": deliverable, "deliverable_hash": t.deliverable_hash,
            "approved": bool(approvals), "approval_refs": approvals,
        })
        refs += [r for r in (deliverable, *approvals) if r]
    return {"dispute_ref": f"dispute:{d.id}", "status": d.status, "tasks": records, "refs": refs}


def validate_summary(summary: DisputeSummary, refs: list[str]) -> list[str]:
    """9-2 の検証。違反項目の一覧（空なら合格）。モデルの出力値は入れない（CG-007）。
    結論の混入はスキーマ（extra="forbid"）で弾く。ここでは件数と参照を確かめる。"""
    out: list[str] = []
    if not summary.issues:
        out.append("There are no issues")
    known = set(refs)
    no_ref = [i for i, x in enumerate(summary.issues, 1) if not x.evidence_refs]
    if no_ref:
        out.append(f"Some issues have no reference to a record (items {', '.join(str(i) for i in no_ref[:10])})")
    bad = [i for i, x in enumerate(summary.issues, 1) if any(r not in known for r in x.evidence_refs)]
    if bad:
        out.append(f"Some issues reference records that were not provided (items {', '.join(str(i) for i in bad[:10])})")
    return out


def _allowed_dispute(ctx: ToolContext, dispute_id: str) -> Dispute:
    d = ctx.db.get(Dispute, dispute_id)
    if d is None:
        raise ToolError("Dispute not found")
    if ctx.run.dispute_id != dispute_id and ctx.run.case_id != d.case_id:
        raise ToolError("Only the dispute linked to this run can be handled")
    return d


@register("TOOL-003")
def read_dispute_record(ctx: ToolContext, *, dispute_id: str) -> dict:
    _allowed_dispute(ctx, dispute_id)
    return dispute_record(ctx.db, dispute_id)


@register("TOOL-007")
def save_dispute_summary(ctx: ToolContext, *, dispute_id: str, revision: int, issues: list[dict]) -> dict:
    _allowed_dispute(ctx, dispute_id)
    if revision < 1:
        raise ToolError("The revision number must be 1 or greater")
    try:
        summary = DisputeSummary.model_validate({"issues": issues})
    except ValueError as e:
        raise ToolError(f"The dispute summary has an invalid format: {e}") from e
    violations = validate_summary(summary, dispute_record(ctx.db, dispute_id)["refs"])
    if violations:  # 9-2: 検証に通らない出力は保存しない
        raise ToolError("The dispute summary failed validation: " + " / ".join(violations))
    trace.save_output(ctx.db, "dispute_summary", dispute_id, revision, summary.model_dump(), ctx.run)
    return {"dispute_id": dispute_id, "revision": revision, "issue_count": len(summary.issues)}
