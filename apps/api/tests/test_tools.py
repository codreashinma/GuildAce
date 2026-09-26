"""ツールの実行基盤と権限（WP-006 / GRD-001・GRD-008・CG-006・TOOL-001）。"""

import json
from pathlib import Path

import pytest

from app.agents import tool_read, tools, trace  # noqa: F401  tool_read は TOOL-001 を登録する
from app.agents.tools import ALLOWED, TOOLS, ToolError, call_tool
from app.models import Agent, AgentToolCall, Case, Dispute, Task, User

CLIENT = "0x" + "c1" * 20
APPROVER = "0x" + "a1" * 20
PAYEE = "0x" + "b2" * 20
NULLIFIER = "0x" + "9f" * 32


@pytest.fixture
def case(db):
    client = User(wallet_address=CLIENT)
    creator = User(wallet_address="0x" + "d4" * 20)
    db.add_all([client, creator])
    db.flush()
    agent = Agent(creator_id=creator.id, name="Web PM", label="web-pm", category="web", payout_address=PAYEE, status="published")
    db.add(agent)
    db.flush()
    c = Case(client_id=client.id, agent_id=agent.id, title="EC サイト", description="商品を売りたい", budget=300_000_000,
             status="in_progress", escrow_case_id="0x" + "00" * 32, approvers=[APPROVER], threshold=1, request_nullifier=NULLIFIER)
    db.add(c)
    db.flush()
    db.add_all([
        Task(case_id=c.id, order_no=1, title="フロント実装", type="ai", role="frontend", estimated_cost=120_000_000, payee=PAYEE, deliverable="成果物の本文です"),
        Task(case_id=c.id, order_no=0, title="画面設計", type="ai", role="designer", estimated_cost=80_000_000),
    ])
    db.commit()
    return c


@pytest.fixture
def fake_impl(monkeypatch):
    """ツールの実装を差し替え、呼ばれた回数を数える。"""
    calls: list[dict] = []

    def install(tool_id, fn=None):
        def impl(ctx, **args):
            calls.append(args)
            return fn(len(calls)) if fn else {"ok": True}
        monkeypatch.setitem(tools._IMPLS, tool_id, impl)
        return calls

    return install


# ---------------------------------------------------------------- GRD-001: 許可リスト


def test_allowed_matches_design_6_2():
    assert ALLOWED["AG-001"] == {"TOOL-001", "TOOL-004", "TOOL-005", "TOOL-006", "TOOL-007", "TOOL-008", "TOOL-009"}
    assert ALLOWED["AG-002"] == set()
    assert ALLOWED["AG-003"] == {"TOOL-001", "TOOL-002"}
    assert ALLOWED["AG-004"] == {"TOOL-001", "TOOL-003"}
    assert [t.effect for t in TOOLS.values()].count("irreversible") == 1  # TOOL-009 だけ


@pytest.mark.parametrize("tool_id", list(TOOLS))
def test_grd001_ag002_cannot_call_any_tool(db, fake_impl, tool_id):
    calls = fake_impl(tool_id)
    run = trace.start_run(db, "AG-002")
    r = call_tool(db, run, tool_id)
    assert not r.ok and r.denied
    assert calls == []  # 実装は実行されない
    rec = db.query(AgentToolCall).one()
    assert (rec.tool_id, rec.allowed, rec.ok) == (tool_id, False, False)


def test_grd001_tool_outside_allowlist_is_denied_and_recorded(db, fake_impl):
    calls = fake_impl("TOOL-009")
    run = trace.start_run(db, "AG-003")
    r = call_tool(db, run, "TOOL-009")
    assert r.denied and calls == []
    assert "AG-003 は TOOL-009" in db.query(AgentToolCall).one().error


def test_unknown_tool_is_denied(db):
    run = trace.start_run(db, "AG-001")
    assert call_tool(db, run, "TOOL-099").denied


def test_allowed_but_unimplemented_tool_fails_without_denial(db, monkeypatch):
    monkeypatch.delitem(tools._IMPLS, "TOOL-005", raising=False)
    run = trace.start_run(db, "AG-001")
    r = call_tool(db, run, "TOOL-005")
    assert not r.ok and not r.denied and "未実装" in r.error


# ---------------------------------------------------------------- 再試行（6-2）


def test_read_tool_is_retried_up_to_3_times(db, fake_impl):
    def flaky(n):
        if n < 3:
            raise RuntimeError("一時的な失敗")
        return {"n": n}

    calls = fake_impl("TOOL-003", flaky)
    run = trace.start_run(db, "AG-004")
    r = call_tool(db, run, "TOOL-003")
    assert r.ok and r.attempts == 3 and len(calls) == 3
    assert db.query(AgentToolCall).count() == 1  # 1 回の呼び出しとして記録


def test_irreversible_tool_is_not_retried(db, fake_impl):
    def boom(_n):
        raise RuntimeError("送信に失敗")

    calls = fake_impl("TOOL-009", boom)
    run = trace.start_run(db, "AG-001")
    r = call_tool(db, run, "TOOL-009")
    assert not r.ok and r.attempts == 1 and len(calls) == 1


def test_tool_error_is_not_retried(db, fake_impl):
    def refuse(_n):
        raise ToolError("対象の外です")

    calls = fake_impl("TOOL-003", refuse)
    run = trace.start_run(db, "AG-004")
    r = call_tool(db, run, "TOOL-003")
    assert not r.ok and r.error == "対象の外です" and len(calls) == 1


# ---------------------------------------------------------------- TOOL-001 read_project_context


def test_tool001_returns_only_the_bound_case_without_addresses_or_amounts(db, case):
    run = trace.start_run(db, "AG-003", case_id=case.id)
    r = call_tool(db, run, "TOOL-001", case_id=case.id)
    assert r.ok
    v = r.value
    assert v["budget_amount"] == "300000000" and v["approver_count"] == 1
    assert [t["seq"] for t in v["tasks"]] == [1, 2] and v["tasks"][0]["title"] == "画面設計"
    dumped = json.dumps(v, ensure_ascii=False).lower()
    for secret in (CLIENT, APPROVER, PAYEE, NULLIFIER, "成果物の本文です", "120000000", "estimated_cost", "payee"):
        assert secret.lower() not in dumped


def test_tool001_rejects_other_case(db, case):
    other = Case(client_id=case.client_id, agent_id=case.agent_id, title="別の案件", budget=1, status="in_progress", escrow_case_id="0x" + "11" * 32)
    db.add(other)
    db.commit()
    run = trace.start_run(db, "AG-001", case_id=other.id)
    r = call_tool(db, run, "TOOL-001", case_id=case.id)
    assert not r.ok and "以外は読めません" in r.error


def test_tool001_rejects_run_without_case(db, case):
    run = trace.start_run(db, "AG-001")
    assert not call_tool(db, run, "TOOL-001", case_id=case.id).ok


def test_tool001_dispute_run_reads_its_case(db, case):
    d = Dispute(case_id=case.id, reason="不足がある", status="open")
    db.add(d)
    db.commit()
    run = trace.start_run(db, "AG-004", dispute_id=d.id)
    assert call_tool(db, run, "TOOL-001", case_id=case.id).ok


# ---------------------------------------------------------------- GRD-008


def test_grd008_no_tool_writes_human_verification():
    assert not any("verif" in t.name or "world" in t.name for t in TOOLS.values())
    agents_dir = Path(tools.__file__).parent
    for src in agents_dir.glob("*.py"):
        text = src.read_text(encoding="utf-8")
        assert "WorldVerification" not in text and "world_verifications" not in text, src.name
