"""エージェントの実行記録と出力の保存（WP-005 / agent-orchestration 10・12 章、agent-infra 8 章）。
記録先は DB のテーブル（agent_runs / agent_tool_calls / agent_outputs）。INF-008（可観測性ストア）の代わり（DEC-010）。
記録してはいけないもの（12-2・8-2）: 依頼文や主張の全文、鍵・API キー・接続情報。全文は入れず長さと先頭だけを残し、
記録する文字列は必ず redact を通す。"""

import re
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AgentOutput, AgentRun, AgentToolCall
from .context import Truncation
from .llm import LLMResult

OUTPUT_KINDS = ("task_plan", "team_proposal", "dispute_summary")  # TOOL-004 / 005 / 007
RUN_STATUSES = ("queued", "running", "done", "failed", "stopped")  # queued は AG-001 の実行のジョブ行（WP-017）
SUMMARY_HEAD = 40

# 8-2: 鍵の形（0x + 64 桁。秘密鍵・World の nullifier も同じ形）、Google の API キー、JWT、接続文字列の認証部分
_SECRET_PATTERNS = [
    (re.compile(r"0x[0-9a-fA-F]{64}"), "[REDACTED_HEX64]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[REDACTED_API_KEY]"),
    (re.compile(r"eyJ[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def summarize_input(text: str) -> str:
    """12-1「入力の要約（依頼文の原文は含めない）」: 長さと先頭だけ。"""
    head = redact(text[:SUMMARY_HEAD]).replace("\n", " ")
    return f"{len(text)} chars: {head}{'…' if len(text) > SUMMARY_HEAD else ''}"


# ---------------------------------------------------------------- 実行（agent_runs）


def start_run(db: Session, agent_id: str, *, mode: str | None = None, case_id: str | None = None, dispute_id: str | None = None,
              parent_run_id: str | None = None, input_text: str | None = None) -> AgentRun:
    run = AgentRun(agent_id=agent_id, mode=mode, case_id=case_id, dispute_id=dispute_id, parent_run_id=parent_run_id,
                   status="running", input_summary=summarize_input(input_text) if input_text is not None else None,
                   validation_failures=[], truncations=[])
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def enqueue_run(db: Session, mode: str, *, case_id: str | None = None, dispute_id: str | None = None,
                input_text: str | None = None) -> AgentRun | None:
    """AG-001 の実行を「待ち」として入れる（WP-017 / DEC-008。ジョブ行）。同じ案件・紛争・モードで待ち・実行中の
    ものがあれば入れずに None（agent_runs の部分一意索引。1 案件 1 実行。agent-infra 5 章）。"""
    run = AgentRun(agent_id="AG-001", mode=mode, case_id=case_id, dispute_id=dispute_id, status="queued",
                   input_summary=summarize_input(input_text) if input_text is not None else None, validation_failures=[], truncations=[])
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(run)
    return run


def record_llm(db: Session, run: AgentRun, result: LLMResult, truncations: list[Truncation] | None = None) -> None:
    """LLM を 1 回呼んだ結果を積み上げる（呼び出し回数・トークン数・検証失敗・切り詰め）。"""
    run.iterations += 1
    run.input_tokens += result.input_tokens
    run.output_tokens += result.output_tokens
    if result.failure in ("parse", "schema"):
        run.retries += 1
        # detail は違反項目だけ（モデルの出力値は入っていない。WP-003）
        run.validation_failures = [*(run.validation_failures or []), redact(f"{result.failure}: {result.detail}")[:1000]]
    if truncations:
        run.truncations = [*(run.truncations or []), *(asdict(t) for t in truncations)]
    db.commit()


def finish_run(db: Session, run: AgentRun, status: str, error: str | None = None) -> None:
    if status not in RUN_STATUSES or status == "running":
        raise ValueError(f"Not a terminal status: {status}")
    run.status, run.finished_at = status, datetime.now(UTC)
    run.error = redact(error)[:2000] if error else None
    db.commit()


# ---------------------------------------------------------------- ツール呼び出し（agent_tool_calls）


def record_tool_call(db: Session, run: AgentRun, tool_id: str, *, allowed: bool, ok: bool, duration_ms: int = 0,
                     validation: str | None = None, error: str | None = None) -> AgentToolCall:
    call = AgentToolCall(run_id=run.id, tool_id=tool_id, allowed=allowed, ok=ok, duration_ms=duration_ms,
                         validation=redact(validation)[:2000] if validation else None, error=redact(error)[:2000] if error else None)
    db.add(call)
    db.commit()
    return call


# ---------------------------------------------------------------- 出力（agent_outputs。TOOL-004 / 005 / 007 の保存先）


def save_output(db: Session, kind: str, target_id: str, revision: int, payload: dict, run: AgentRun | None = None) -> AgentOutput:
    """(種類, 対象 ID, 版番号) で冪等に保存する。同じキーが既にあれば上書きする（agent-orchestration 6-2・10 章）。"""
    if kind not in OUTPUT_KINDS:
        raise ValueError(f"Unknown output kind: {kind}")
    row = db.query(AgentOutput).filter_by(kind=kind, target_id=target_id, revision=revision).one_or_none()
    if row is None:
        row = AgentOutput(kind=kind, target_id=target_id, revision=revision, payload=payload, run_id=run.id if run else None)
        db.add(row)
    else:
        row.payload, row.run_id = payload, (run.id if run else row.run_id)
    db.commit()
    db.refresh(row)
    return row


def latest_output(db: Session, kind: str, target_id: str) -> AgentOutput | None:
    return db.query(AgentOutput).filter_by(kind=kind, target_id=target_id).order_by(AgentOutput.revision.desc()).first()


def next_revision(db: Session, kind: str, target_id: str) -> int:
    latest = latest_output(db, kind, target_id)
    return (latest.revision + 1) if latest else 1


def revision_for_run(db: Session, kind: str, target_id: str, run: AgentRun) -> int:
    """この実行がすでに保存した版があればその版、無ければ次の版。再開したときに同じ版へ上書きし、版を増やさない（10 章）。"""
    row = (db.query(AgentOutput).filter_by(kind=kind, target_id=target_id, run_id=run.id)
           .order_by(AgentOutput.revision.desc()).first())
    return row.revision if row else next_revision(db, kind, target_id)
