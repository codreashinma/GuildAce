"""AG-004 紛争論点整理エージェント（WP-012 / agent-definitions AG-004・agent-orchestration 9-2・9-4、context-templates AG-004）。
紛争の主張と対象タスクの記録（TOOL-003）から、争点の一覧（title・双方の立場・evidence_refs）を作る。
- 主張は DEC-011: 発注者 = disputes.reason（CG-004 で打ち切り。context.build_ag004 が行う）、受注者 = 空。要約のための LLM は呼ばない
- 使うツールは TOOL-003 だけ（tools.call_tool 経由。GRD-001・GRD-007 はそこで効く）。保存は AG-001 が TOOL-007 で行う
- 出力は 9-2 で検証し（tool_dispute.validate_summary）、違反項目だけを CTX-008 に入れて再試行する（PMT-016。CG-007）。最大 3 回
- 上限に達しても例外にせず「論点なし」を返す。裁定は人間が行えるため止めない（HIL-004 へ進むのは WP-016・WP-019）
既存の gemini.summarize_dispute と /disputes の流れは変えない（並べて作る）。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from ..models import Dispute
from . import context, control, llm, tools, trace
from .limits import LimitHit
from .tool_dispute import DisputeSummary, validate_summary

MAX_ATTEMPTS = 3  # 9-4: 違反項目を添えて最大 3 回

Reason = Literal["violations", "empty", "limit", "stopped", "record_error", "llm_error", "unavailable"]


@dataclass
class DisputeResult:
    """ok が偽なら「論点なし」。reason と violations が HIL-004 に渡す材料になる"""
    ok: bool
    run_id: str
    summary: DisputeSummary | None = None
    reason: Reason | None = None
    violations: list[str] = field(default_factory=list)
    limit_hit: LimitHit | None = None
    attempts: int = 0

    @property
    def no_issues(self) -> bool:
        return not self.ok


def claims_for(dispute: Dispute) -> list[dict]:
    """DEC-011: 発注者の主張 = disputes.reason、受注者の主張 = 空（入力する手段が無い）。打ち切りは build_ag004 の CG-004。"""
    return [{"party": "requester", "summary": dispute.reason or ""}, {"party": "provider", "summary": ""}]


def default_mock(record: dict) -> Callable[[], dict]:
    """GEMINI_API_KEY が無いときの決定的な応答: 参照できる記録があれば 1 件の争点、無ければ空。"""
    refs = record["refs"][:1]
    issues = [{"title": "成果物が依頼の条件を満たしているか", "requester_position": "条件を満たしていないと主張",
               "provider_position": "主張の入力なし", "evidence_refs": refs}] if refs else []
    return lambda: {"issues": issues}


def analyze(db: Session, *, dispute_id: str, parent_run_id: str | None = None,
            mock: Callable[[], str | dict] | None = None) -> DisputeResult:
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise ValueError(f"紛争がありません: {dispute_id}")
    run = trace.start_run(db, "AG-004", mode="analyze_dispute", dispute_id=dispute_id, parent_run_id=parent_run_id, input_text=d.reason or "")

    def finish(result: DisputeResult, status: str) -> DisputeResult:
        detail = None if result.ok else f"{result.reason}: " + " / ".join(result.violations or ([result.limit_hit.detail] if result.limit_hit else []))
        trace.finish_run(db, run, status, error=detail)
        return result

    got = tools.call_tool(db, run, "TOOL-003", dispute_id=dispute_id)  # 停止（GRD-007）と許可（GRD-001）は call_tool が確かめる
    if got.stopped:
        return finish(DisputeResult(False, run.id, reason="stopped"), "stopped")
    if not got.ok:
        return finish(DisputeResult(False, run.id, reason="record_error", violations=[got.error or ""]), "failed")
    record = got.value
    task_record = {k: v for k, v in record.items() if k != "refs"}
    claims = claims_for(d)
    mock = mock or default_mock(record)
    violations: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if control.state_for_run(db, run).stopped:  # GRD-007: 次の LLM 呼び出しの前にも確かめる
            return finish(DisputeResult(False, run.id, reason="stopped", violations=violations, attempts=attempt - 1), "stopped")
        ctx = context.build_ag004(task_record=task_record, claims=claims, schema=DisputeSummary, violations=violations)
        r = llm.call_structured(db=db, run=run, agent_id="AG-004", system=ctx.system, contents=ctx.contents, schema=DisputeSummary, mock=mock)
        if r.failure == "limit":
            status = "stopped" if r.limit_hit and r.limit_hit.kind.startswith("cost") else "failed"
            return finish(DisputeResult(False, run.id, reason="limit", violations=violations, limit_hit=r.limit_hit, attempts=attempt - 1), status)
        trace.record_llm(db, run, r, ctx.truncations)
        if r.failure in ("timeout", "error", "unavailable"):
            reason: Reason = "unavailable" if r.failure == "unavailable" else "llm_error"
            return finish(DisputeResult(False, run.id, reason=reason, violations=[f"{r.failure}: {r.detail}"], attempts=attempt), "failed")
        if r.failure in ("parse", "schema"):  # CG-005: 結論などスキーマ外のキーを含む出力もここで弾く
            violations = [f"出力の形が合いません（{r.failure}）: {r.detail}"]
            continue
        if not r.output.issues:  # PMT-004・012: 判断できないときは空の一覧。推測で争点を作らせず、再試行しない
            return finish(DisputeResult(False, run.id, reason="empty", violations=["争点が 1 件もありません（主張と記録から判断できない）"],
                                        attempts=attempt), "done")
        violations = validate_summary(r.output, record["refs"])  # 9-2（決定的なコード）
        if not violations:
            return finish(DisputeResult(True, run.id, summary=r.output, attempts=attempt), "done")
    # 9-4: 上限に達したら論点なしのまま（HIL-004 へ進むのは AG-001。WP-016）
    return finish(DisputeResult(False, run.id, reason="violations", violations=violations, attempts=MAX_ATTEMPTS), "failed")
