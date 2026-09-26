"""実行記録と出力の保存（WP-005 / INF-008 の代替・TOOL-004 / 005 / 007 の保存先・12 章）。"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents import trace
from app.agents.context import Truncation
from app.agents.llm import LLMResult
from app.models import AgentOutput, AgentRun, AgentToolCall

SECRET_KEY = "0x" + "ab" * 32
API_KEY = "AIza" + "x" * 35


def test_tables_are_created_by_create_all(db):
    assert db.query(AgentRun).count() == 0
    assert db.query(AgentToolCall).count() == 0
    assert db.query(AgentOutput).count() == 0


# ---------------------------------------------------------------- 12-2 / 8-2: 記録してはいけないもの


@pytest.mark.parametrize("secret, marker", [
    (SECRET_KEY, "[REDACTED_HEX64]"),
    (API_KEY, "[REDACTED_API_KEY]"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "[REDACTED_JWT]"),
    ("postgresql+psycopg://user:pass@db:5432/choice", "[REDACTED]@"),
])
def test_redact_removes_secret_shapes(secret, marker):
    out = trace.redact(f"前 {secret} 後")
    assert secret not in out and marker in out


def test_input_summary_keeps_only_length_and_head():
    text = "EC サイトを作りたい。" + "詳しい要件" * 200
    s = trace.summarize_input(text)
    assert s.startswith(f"{len(text)} chars: ") and s.endswith("…")
    assert "詳しい要件" * 20 not in s  # 全文を残さない
    assert len(s) < 80


def test_start_run_does_not_store_full_text_or_secrets(db):
    run = trace.start_run(db, "AG-002", mode="decompose", input_text=f"{SECRET_KEY} を含む依頼。" + "あ" * 500)
    stored = db.get(AgentRun, run.id)
    assert SECRET_KEY not in stored.input_summary and "あ" * 100 not in stored.input_summary
    assert stored.status == "running" and stored.agent_id == "AG-002"


# ---------------------------------------------------------------- 12-1: 記録する項目


def test_record_llm_accumulates_tokens_retries_and_truncations(db):
    run = trace.start_run(db, "AG-003", mode="form_team")
    trace.record_llm(db, run, LLMResult(None, "schema", "items.0.amount: 整数ではありません", 100, 20),
                     [Truncation("CTX-007", "items", 30, 20)])
    trace.record_llm(db, run, LLMResult(object(), None, "", 90, 25))
    stored = db.get(AgentRun, run.id)
    assert (stored.iterations, stored.retries, stored.input_tokens, stored.output_tokens) == (2, 1, 190, 45)
    assert stored.validation_failures == ["schema: items.0.amount: 整数ではありません"]
    assert stored.truncations == [{"ctx_id": "CTX-007", "unit": "items", "before": 30, "after": 20}]


def test_finish_run_sets_status_and_redacts_error(db):
    run = trace.start_run(db, "AG-001")
    trace.finish_run(db, run, "failed", error=f"鍵 {SECRET_KEY} で失敗")
    stored = db.get(AgentRun, run.id)
    assert stored.status == "failed" and stored.finished_at is not None
    assert SECRET_KEY not in stored.error
    with pytest.raises(ValueError):
        trace.finish_run(db, run, "running")


def test_record_tool_call_keeps_denied_calls(db):
    run = trace.start_run(db, "AG-002")
    trace.record_tool_call(db, run, "TOOL-004", allowed=False, ok=False, error="AG-002 は TOOL-004 を呼べません")
    call = db.query(AgentToolCall).one()
    assert (call.run_id, call.tool_id, call.allowed, call.ok) == (run.id, "TOOL-004", False, False)


def test_parent_run_links_delegation(db):
    parent = trace.start_run(db, "AG-001", mode="decompose")
    child = trace.start_run(db, "AG-002", parent_run_id=parent.id)
    assert db.get(AgentRun, child.id).parent_run_id == parent.id


# ---------------------------------------------------------------- TOOL-004 / 005 / 007 の冪等な保存


def test_save_output_is_idempotent_and_overwrites_same_revision(db):
    a = trace.save_output(db, "task_plan", "case-1", 1, {"tasks": [{"seq": 1}]})
    b = trace.save_output(db, "task_plan", "case-1", 1, {"tasks": [{"seq": 1}, {"seq": 2}]})
    assert a.id == b.id
    assert db.query(AgentOutput).count() == 1
    assert db.get(AgentOutput, a.id).payload == {"tasks": [{"seq": 1}, {"seq": 2}]}


def test_same_revision_cannot_exist_twice_in_db(db):
    """一意制約 (kind, target_id, revision) が DB にある。save_output を通さない二重挿入は弾かれる。"""
    db.add(AgentOutput(kind="team_proposal", target_id="case-1", revision=1, payload={}))
    db.commit()
    db.add(AgentOutput(kind="team_proposal", target_id="case-1", revision=1, payload={}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_revisions_and_kinds_are_separate(db):
    trace.save_output(db, "task_plan", "case-1", 1, {"v": 1})
    trace.save_output(db, "task_plan", "case-1", 2, {"v": 2})
    trace.save_output(db, "team_proposal", "case-1", 1, {"v": "team"})
    assert trace.latest_output(db, "task_plan", "case-1").payload == {"v": 2}
    assert trace.next_revision(db, "task_plan", "case-1") == 3
    assert trace.next_revision(db, "dispute_summary", "dispute-1") == 1


def test_unknown_output_kind_is_rejected(db):
    with pytest.raises(ValueError):
        trace.save_output(db, "funding", "case-1", 1, {})
