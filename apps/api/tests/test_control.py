"""キルスイッチ（WP-007 / GRD-007・OPS-001〜003）。"""

import importlib.util
from pathlib import Path

import pytest

from app.agents import control, tools, trace
from app.agents.control import AgentStopped
from app.agents.tools import call_tool
from app.models import Agent, AgentControl, AgentToolCall, Case, Dispute, User

SECRET_KEY = "0x" + "ab" * 32


def _agent_ops():
    path = Path(__file__).resolve().parent.parent / "scripts" / "agent_ops.py"
    spec = importlib.util.spec_from_file_location("agent_ops", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cases(db):
    u = User(wallet_address="0x" + "c1" * 20)
    db.add(u)
    db.flush()
    a = Agent(creator_id=u.id, name="PM", label="pm", category="web", payout_address=u.wallet_address, status="published")
    db.add(a)
    db.flush()
    made = [Case(client_id=u.id, agent_id=a.id, title=t, budget=1, status="in_progress", escrow_case_id="0x" + f"{i:02d}" * 32)
            for i, t in enumerate(("案件 A", "案件 B"))]
    db.add_all(made)
    db.commit()
    return made


@pytest.fixture
def counted(monkeypatch):
    """TOOL-001 の実装を差し替え、呼ばれた回数を数える。"""
    calls = []
    monkeypatch.setitem(tools._IMPLS, "TOOL-001", lambda ctx, **a: calls.append(a) or {"ok": True})
    return calls


def _call(db, case, agent="AG-001", dispute=None):
    run = trace.start_run(db, agent, case_id=None if dispute else case.id, dispute_id=dispute.id if dispute else None)
    return call_tool(db, run, "TOOL-001", case_id=case.id)


# ---------------------------------------------------------------- GRD-007: 止まっている間はツールを実行しない


def test_grd007_global_stop_blocks_tool_calls(db, cases, counted):
    control.stop(db, reason="暴走の疑い", operator="ops")
    r = _call(db, cases[0])
    assert not r.ok and r.stopped and "global" in r.error
    assert counted == []  # 実装は呼ばれない
    rec = db.query(AgentToolCall).one()
    assert (rec.ok, rec.allowed) == (False, True)


def test_grd007_case_stop_blocks_only_that_case(db, cases, counted):
    a, b = cases
    control.stop(db, case_id=a.id, reason="この案件だけおかしい", operator="ops")
    assert _call(db, a).stopped
    assert _call(db, b).ok  # 他の案件は動き続ける（OPS-002 の確認方法）
    assert len(counted) == 1


def test_grd007_dispute_run_follows_its_case_stop(db, cases, counted):
    a = cases[0]
    d = Dispute(case_id=a.id, reason="不足", status="open")
    db.add(d)
    db.commit()
    control.stop(db, case_id=a.id, reason="紛争が荒れている", operator="ops")
    assert _call(db, a, agent="AG-004", dispute=d).stopped
    assert counted == []


def test_ops003_resume_restores_tool_calls(db, cases, counted):
    control.stop(db, reason="調査", operator="ops")
    assert _call(db, cases[0]).stopped
    control.resume(db, reason="原因を取り除いた", operator="ops")
    assert _call(db, cases[0]).ok


def test_resume_all_does_not_clear_case_stop(db, cases, counted):
    a = cases[0]
    control.stop(db, case_id=a.id, reason="案件の問題", operator="ops")
    control.stop(db, reason="全体の問題", operator="ops")
    control.resume(db, reason="全体は解消", operator="ops")
    s = control.state(db, a.id)
    assert s.stopped and s.scope == control.case_scope(a.id)
    assert not control.state(db, cases[1].id).stopped


def test_ensure_running_raises_before_delegation(db, cases):
    control.ensure_running(db, cases[0].id)  # 止まっていなければ何もしない
    control.stop(db, case_id=cases[0].id, reason="止める", operator="ops")
    with pytest.raises(AgentStopped, match="Stopped"):
        control.ensure_running(db, cases[0].id)


# ---------------------------------------------------------------- 操作の記録（OPS-001〜003 の「記録する」）


def test_operations_are_kept_as_history_and_reason_is_required(db, cases):
    with pytest.raises(ValueError):
        control.stop(db, reason=" ", operator="ops")
    control.stop(db, reason=f"鍵 {SECRET_KEY} が漏れた疑い", operator="alice")
    control.resume(db, reason="取り替え済み", operator="bob")
    rows = db.query(AgentControl).order_by(AgentControl.created_at).all()
    assert [(r.action, r.operator) for r in rows] == [("stop", "alice"), ("resume", "bob")]
    assert SECRET_KEY not in rows[0].reason  # 理由も伏せ字を通す
    assert control.stopped_scopes(db) == []


# ---------------------------------------------------------------- 管理用スクリプト


def test_agent_ops_script_stop_status_resume(db, cases, capsys):
    ops = _agent_ops()
    assert ops.main(["stop-case", cases[0].id, "--reason", "調査のため", "--operator", "ops"]) == 0
    assert ops.main(["status"]) == 0
    out = capsys.readouterr().out
    assert f"stopped  case:{cases[0].id}" in out and "調査のため" in out
    assert ops.main(["resume-case", cases[0].id, "--operator", "ops"]) == 0
    ops.main(["status"])
    assert "No scopes are stopped" in capsys.readouterr().out


def test_agent_ops_script_requires_reason_for_stop(db):
    with pytest.raises(SystemExit):
        _agent_ops().main(["stop-all"])
