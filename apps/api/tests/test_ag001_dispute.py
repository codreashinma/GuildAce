"""AG-001 紛争の委譲と進捗の更新（WP-016 / AG-001・TOOL-006・HIL-004・13-3）。LLM はモック。"""

import copy

import pytest

from app.agents import ag001_orchestrator as ag001
from app.agents import control, tools, trace
from app.agents.ag001_orchestrator import Ag001Step, _State, run_dispute, validate_step
from app.agents.tool_dispute import dispute_record
from app.models import Agent, AgentOutput, AgentRun, AgentToolCall, Case, Dispute, Task, User


@pytest.fixture
def dispute(db):
    u = User(wallet_address="0x" + "b1" * 20)
    db.add(u)
    db.flush()
    a = Agent(creator_id=u.id, name="PM", label="pm", category="web", payout_address=u.wallet_address, status="published")
    db.add(a)
    db.flush()
    c = Case(client_id=u.id, agent_id=a.id, title="予約サイト", budget=1, status="in_progress", escrow_case_id="0x" + "14" * 32)
    db.add(c)
    db.flush()
    db.add_all([Task(case_id=c.id, order_no=0, title="画面", type="ai", role="designer", status="done", chain_status="submitted",
                     deliverable_hash="0x" + "d1" * 32),
                Task(case_id=c.id, order_no=1, title="実装", type="ai", role="backend", status="todo", chain_status="funded")])
    d = Dispute(case_id=c.id, reason="予約機能が無い", status="open")
    db.add(d)
    db.commit()
    return d


def _issues(db, d, refs=None):
    refs = refs if refs is not None else dispute_record(db, d.id)["refs"][:1]
    return {"issues": [{"title": "予約機能", "requester_position": "無い", "provider_position": "主張なし", "evidence_refs": refs}]}


def fixed(value):
    return lambda: copy.deepcopy(value)


def _summaries(db):
    return db.query(AgentOutput).filter(AgentOutput.kind == "dispute_summary").all()


# ---------------------------------------------------------------- 紛争モード（13-3）


def test_dispute_mode_saves_summary(db, dispute):
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed(_issues(db, dispute)))
    assert r.ok and r.summary_revision == 1 and not r.no_issues
    [row] = _summaries(db)
    assert row.target_id == dispute.id and row.payload == _issues(db, dispute)
    run = db.get(AgentRun, r.run_id)
    assert (run.agent_id, run.mode, run.status, run.iterations) == ("AG-001", "analyze_dispute", "done", 3)
    assert [x.agent_id for x in db.query(AgentRun).filter(AgentRun.parent_run_id == run.id)] == ["AG-004"]
    assert [t.tool_id for t in db.query(AgentToolCall).filter(AgentToolCall.run_id == run.id)] == ["TOOL-007"]


def test_ag004_failure_returns_no_issues_without_exception(db, dispute):
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed(_issues(db, dispute, refs=["deliverable:でっちあげ"])))
    assert not r.ok and r.no_issues and r.reason == "violations" and r.summary_revision is None
    assert _summaries(db) == []
    assert db.get(AgentRun, r.run_id).status == "done"  # 論点なしは正常な終わり方（HIL-004 へ進む）


def test_ag004_empty_returns_no_issues(db, dispute):
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed({"issues": []}))
    assert r.no_issues and r.reason == "empty"


def test_hil004_is_not_blocked_no_reconfirmation_and_dispute_untouched(db, dispute, monkeypatch):
    """紛争では HIL-005（TOOL-008）へ差し戻さない。AG-001 が受理できない指定を続けても論点なしで返す。"""
    monkeypatch.setattr(ag001, "expected_step", lambda st: {"action": "finish"})  # 最初に終えようとし続ける
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed(_issues(db, dispute)))
    assert r.no_issues and r.reason == "orchestrator"
    assert db.query(AgentToolCall).filter(AgentToolCall.tool_id == "TOOL-008").count() == 0
    db.expire_all()
    d = db.get(Dispute, dispute.id)
    assert (d.status, d.summary_json) == ("open", None)  # 既存の紛争の状態と summary_json は変えない
    assert db.get(Case, dispute.case_id).status == "in_progress"


def test_stopped_returns_no_issues(db, dispute):
    control.stop(db, case_id=dispute.case_id, reason="確認", operator="test")
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed(_issues(db, dispute)))
    assert r.no_issues and r.reason == "stopped"
    assert db.query(AgentRun).filter(AgentRun.agent_id == "AG-004").count() == 0


def test_modes_do_not_mix():
    """計画の操作は紛争モードで、紛争の操作は計画モードで受理しない（ALLOWED）。"""
    assert validate_step(Ag001Step(action="delegate_decompose"), _State(phase="dispute_start"))
    assert validate_step(Ag001Step(action="delegate_analyze_dispute"), _State(phase="start"))
    assert validate_step(Ag001Step(action="delegate_analyze_dispute"), _State(phase="dispute_start")) == []


def test_tampered_dispute_summary_is_rejected(db, dispute, monkeypatch):
    real, done = ag001.expected_step, []

    def step(st):
        s = real(st)
        if "dispute_summary" in s and not done:
            done.append(1)
            s["dispute_summary"]["issues"][0]["requester_position"] = "発注者が正しい"  # 結論を書き足して返す
        return s

    monkeypatch.setattr(ag001, "expected_step", step)
    r = run_dispute(db, dispute_id=dispute.id, mock_ag004=fixed(_issues(db, dispute)))
    assert r.ok and done
    assert _summaries(db)[0].payload["issues"][0]["requester_position"] == "無い"  # 保存は手元の出力


# ---------------------------------------------------------------- TOOL-006


def test_tool006_uses_existing_projection_and_is_idempotent(db, dispute):
    t = db.query(Task).filter(Task.case_id == dispute.case_id, Task.order_no == 0).one()
    t.chain_status = "disputed"
    db.commit()
    run = trace.start_run(db, "AG-001", case_id=dispute.case_id)
    first = tools.call_tool(db, run, "TOOL-006", task_id=t.id)
    second = tools.call_tool(db, run, "TOOL-006", task_id=t.id)
    assert first.ok and first.value["status"] == "disputed" and first.value["changed"]
    assert second.ok and second.value["status"] == "disputed" and not second.value["changed"]
    db.expire_all()
    assert db.get(Case, dispute.case_id).status == "disputed"


def test_tool006_does_not_take_a_status_from_the_agent(db, dispute):
    t = db.query(Task).filter(Task.case_id == dispute.case_id).first()
    run = trace.start_run(db, "AG-001", case_id=dispute.case_id)
    res = tools.call_tool(db, run, "TOOL-006", task_id=t.id, status="completed")
    assert not res.ok  # 状態の値は受け取らない（判断をしない）
    assert db.get(Case, dispute.case_id).status == "in_progress"


def test_tool006_other_case_and_other_agents_are_rejected(db, dispute):
    t = db.query(Task).filter(Task.case_id == dispute.case_id).first()
    other = Case(client_id=dispute.case.client_id, agent_id=dispute.case.agent_id, title="別", budget=1, status="in_progress",
                 escrow_case_id="0x" + "15" * 32)
    db.add(other)
    db.commit()
    assert not tools.call_tool(db, trace.start_run(db, "AG-001", case_id=other.id), "TOOL-006", task_id=t.id).ok
    for agent_id in ("AG-002", "AG-003", "AG-004"):
        assert tools.call_tool(db, trace.start_run(db, agent_id, case_id=dispute.case_id), "TOOL-006", task_id=t.id).denied
