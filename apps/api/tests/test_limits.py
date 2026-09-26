"""コスト・反復・時間・件数の上限（WP-008 / GRD-003〜005・agent-orchestration 11 章）。
完了条件: 上限に達した後に LLM の呼び出し（モックを含む）が 1 件も起きないこと。"""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.agents import limits, llm, trace
from app.config import get_settings
from app.models import Agent, AgentRun, Case, Dispute, User


class Out(BaseModel):
    title: str


@pytest.fixture
def cases(db):
    u = User(wallet_address="0x" + "d1" * 20)
    db.add(u)
    db.flush()
    a = Agent(creator_id=u.id, name="PM", label="pm", category="web", payout_address=u.wallet_address, status="published")
    db.add(a)
    db.flush()
    made = [Case(client_id=u.id, agent_id=a.id, title=t, budget=1, status="planning", escrow_case_id="0x" + f"{i:02d}" * 32)
             for i, t in enumerate(("案件 A", "案件 B"))]
    db.add_all(made)
    db.commit()
    return made


@pytest.fixture
def counted():
    """モックの応答を返し、呼ばれた回数を数える（LLM を呼んだ回数の代わり）。"""
    calls = []

    def mock():
        calls.append(1)
        return {"title": "x"}

    mock.calls = calls
    return mock


def _call(db, run, mock, **kw):
    return llm.call_structured(db=db, run=run, agent_id=run.agent_id, system="指示", contents="データ", schema=Out, mock=mock, **kw)


def _spent(db, tokens, *, case=None, dispute=None, started_at=None):
    """過去の実行で tokens だけ消費したことにする。"""
    run = AgentRun(agent_id="AG-002", case_id=case.id if case else None, dispute_id=dispute.id if dispute else None,
                   status="done", input_tokens=tokens, output_tokens=0, validation_failures=[], truncations=[])
    if started_at:
        run.started_at = started_at
    db.add(run)
    db.commit()
    return run


def test_defaults_follow_dec004():
    s = get_settings()
    assert [limits.max_iterations(a) for a in ("AG-001", "AG-002", "AG-003", "AG-004")] == [30, 3, 5, 5]
    assert [limits.run_time_limit_s(a) for a in ("AG-001", "AG-002", "AG-003", "AG-004")] == [600, 120, 180, 180]
    assert (s.agent_max_tasks_per_case, s.agent_max_reconfirms_per_case) == (20, 3)
    assert (s.agent_cost_tokens_per_case, s.agent_cost_tokens_per_day) == (200_000, 5_000_000)


# ---------------------------------------------------------------- 11 章: 反復


@pytest.mark.parametrize("agent_id, cap", [("AG-002", 3), ("AG-003", 5), ("AG-004", 5)])
def test_iterations_stop_at_cap_and_no_call_after(db, cases, counted, agent_id, cap):
    run = trace.start_run(db, agent_id, case_id=cases[0].id)
    results = []
    for _ in range(cap + 2):
        r = _call(db, run, counted)
        results.append(r)
        if r.failure != "limit":
            trace.record_llm(db, run, r)
    assert len(counted.calls) == cap
    assert all(r.ok for r in results[:cap])
    assert all(r.failure == "limit" and r.limit_hit.kind == "iterations" for r in results[cap:])
    assert results[cap].limit_hit.used == cap and results[cap].limit_hit.limit == cap


# ---------------------------------------------------------------- 11 章: 時間


def test_time_limit_stops_before_calling(db, cases, counted):
    run = trace.start_run(db, "AG-002", case_id=cases[0].id)
    run.started_at = datetime.now(UTC) - timedelta(seconds=121)
    db.commit()
    r = _call(db, run, counted)
    assert r.failure == "limit" and r.limit_hit.kind == "time" and r.limit_hit.limit == 120
    assert counted.calls == []


def test_call_timeout_is_capped_by_remaining_run_time(db, cases, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "dummy")
    seen = []
    monkeypatch.setattr(llm, "_client", lambda: SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda **kw: seen.append(kw) or SimpleNamespace(text='{"title": "x"}', usage_metadata=None))))
    run = trace.start_run(db, "AG-002", case_id=cases[0].id)
    run.started_at = datetime.now(UTC) - timedelta(seconds=100)
    db.commit()
    assert _call(db, run, None).ok
    assert seen[0]["config"].http_options.timeout <= 20 * 1000  # 残り約 20 秒


# ---------------------------------------------------------------- GRD-005: 案件あたりのトークン数


def test_grd005_case_cost_limit_stops_before_calling(db, cases, counted):
    a, b = cases
    _spent(db, 200_000, case=a)
    r = _call(db, trace.start_run(db, "AG-002", case_id=a.id), counted)
    assert r.failure == "limit" and r.limit_hit.kind == "cost_case"
    assert r.limit_hit.scope == f"case:{a.id}" and r.limit_hit.used == 200_000
    assert counted.calls == []
    # 他の案件は呼べる
    assert _call(db, trace.start_run(db, "AG-002", case_id=b.id), counted).ok
    assert len(counted.calls) == 1


def test_grd005_dispute_runs_count_toward_their_case(db, cases, counted):
    a = cases[0]
    d = Dispute(case_id=a.id, reason="不足", status="open")
    db.add(d)
    db.commit()
    _spent(db, 150_000, case=a)
    _spent(db, 50_000, dispute=d)
    assert limits.case_tokens(db, a.id) == 200_000
    r = _call(db, trace.start_run(db, "AG-004", dispute_id=d.id), counted)
    assert r.failure == "limit" and r.limit_hit.kind == "cost_case"
    assert counted.calls == []


def test_grd005_tokens_recorded_by_calls_reach_the_limit(db, cases, counted, monkeypatch):
    """呼び出しで記録したトークン数（record_llm）がそのまま次の判定に効く。"""
    monkeypatch.setattr(get_settings(), "agent_cost_tokens_per_case", 5)
    run = trace.start_run(db, "AG-003", case_id=cases[0].id)
    r1 = _call(db, run, counted)
    trace.record_llm(db, run, r1)
    assert r1.ok and r1.input_tokens + r1.output_tokens >= 5
    r2 = _call(db, run, counted)
    assert r2.failure == "limit" and r2.limit_hit.kind == "cost_case"
    assert len(counted.calls) == 1


# ---------------------------------------------------------------- GRD-005: 全体（1 日）のトークン数


def test_grd005_global_daily_limit_stops_every_case_and_unbound_runs(db, cases, counted, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_cost_tokens_per_day", 1_000)
    _spent(db, 600, case=cases[0])
    _spent(db, 400)
    for run in (trace.start_run(db, "AG-002", case_id=cases[1].id), trace.start_run(db, "AG-002")):
        r = _call(db, run, counted)
        assert r.failure == "limit" and r.limit_hit.kind == "cost_global" and r.limit_hit.scope == "global"
    assert counted.calls == []


def test_grd005_global_limit_counts_only_today(db, cases, counted, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_cost_tokens_per_day", 1_000)
    _spent(db, 5_000, started_at=datetime.now(UTC) - timedelta(days=1, hours=1))
    assert limits.global_tokens_today(db) == 0
    assert _call(db, trace.start_run(db, "AG-002", case_id=cases[0].id), counted).ok


def test_grd005_warns_at_80_percent(db, cases, counted, caplog):
    a = cases[0]
    _spent(db, 160_000, case=a)
    with caplog.at_level(logging.WARNING, logger=limits.__name__):
        assert _call(db, trace.start_run(db, "AG-002", case_id=a.id), counted).ok
    assert any("GRD-005" in m and f"case:{a.id}" in m for m in caplog.messages)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=limits.__name__):
        assert _call(db, trace.start_run(db, "AG-002", case_id=cases[1].id), counted).ok
    assert caplog.messages == []


def test_real_client_is_not_called_after_limit(db, cases, monkeypatch):
    """本物の経路（偽のクライアント）でも、上限に達したらクライアントを作らない。"""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "dummy")
    made = []
    monkeypatch.setattr(llm, "_client", lambda: made.append(1))
    _spent(db, 200_000, case=cases[0])
    r = _call(db, trace.start_run(db, "AG-002", case_id=cases[0].id), None)
    assert r.failure == "limit" and not r.mocked
    assert made == []


# ---------------------------------------------------------------- GRD-003 / GRD-004: 件数


def test_grd003_task_count():
    assert limits.check_task_count("c1", 20) is None
    hit = limits.check_task_count("c1", 21)
    assert hit.kind == "tasks" and (hit.used, hit.limit) == (21, 20) and "tasks" in hit.detail


def test_grd004_reconfirm_count():
    assert limits.check_reconfirm("c1", 2) is None
    hit = limits.check_reconfirm("c1", 3)
    assert hit.kind == "reconfirms" and (hit.used, hit.limit) == (3, 3)


def test_limits_follow_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_max_tasks_per_case", 5)
    monkeypatch.setattr(get_settings(), "agent_max_iterations_ag002", 1)
    assert limits.check_task_count("c1", 6).limit == 5
    assert limits.max_iterations("AG-002") == 1
