"""AG-001 分解・編成の委譲とエスカレーション（WP-015 / AG-001・TOOL-008・GRD-004・HIL-005・DEC-007 (a)）。LLM と ENS はモック。"""

import copy
import logging

import pytest

from app.agents import ag001_orchestrator as ag001
from app.agents import control, llm, tool_search, tools, trace
from app.agents.ag001_orchestrator import run_planning
from app.models import Agent, AgentOutput, AgentRun, AgentToolCall, Case, Company, Member, Task, User

BUDGET = 1_000_000
AI = "design-bot.choice.eth"
HUMAN = "hanako.photo.eth"
POLICY = {"version": 1, "domain": "web", "workflow": {"phases": [{"key": "designer", "title": "デザイン"}, {"key": "field", "title": "撮影"}]},
          "human_roles": []}
PLAN = {"tasks": [{"seq": 1, "phase": "designer", "title": "画面設計"}, {"seq": 2, "phase": "field", "title": "店舗の撮影"}]}
TEAM = {"items": [{"task_seq": 1, "assignee_ens_name": AI, "amount": "400000"}, {"task_seq": 2, "assignee_ens_name": HUMAN, "amount": "500000"}]}


@pytest.fixture
def case(db, monkeypatch):
    records = {AI: {"codrea.agent.category": "design"}, HUMAN: {"codrea.person.role": "カメラマン", "codrea.person.company": "photo.eth"}}
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {k: v for k, v in records.get(name, {}).items() if k in (keys or [])})
    client, creator, admin = User(wallet_address="0x" + "f1" * 20), User(wallet_address="0x" + "f2" * 20), User(wallet_address="0x" + "f4" * 20)
    db.add_all([client, creator, admin])
    db.flush()
    pm = Agent(creator_id=creator.id, name="PM", label="pm", category="web", payout_address=creator.wallet_address, status="draft",
               fee_bps=200, policy=POLICY)
    bot = Agent(creator_id=creator.id, name="Bot", label="design-bot", category="design", payout_address=creator.wallet_address,
                status="published", ens_name=AI, ens_tx_hash="0x" + "ab" * 32, rating_avg=4, rating_count=1)
    co = Company(admin_id=admin.id, name="撮影会社", ens_name="photo.eth")
    db.add_all([pm, bot, co])
    db.flush()
    db.add(Member(company_id=co.id, label="hanako", name="花子", wallet_address="0x" + "f3" * 20, ens_name=HUMAN, ens_status="written"))
    c = Case(client_id=client.id, agent_id=pm.id, title="撮影つきサイト", description="予約サイトと店舗写真", budget=BUDGET,
             status="planning", escrow_case_id="0x" + "13" * 32)
    db.add(c)
    db.commit()
    return c


def fixed(value):
    return lambda: copy.deepcopy(value)


def _outputs(db, kind):
    return db.query(AgentOutput).filter(AgentOutput.kind == kind).all()


def _reload(db, case):
    db.expire_all()
    return db.get(Case, case.id)


# ---------------------------------------------------------------- 正常


def test_normal_flow_saves_plan_and_team_with_revisions(db, case):
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert r.ok and (r.plan_revision, r.team_revision) == (1, 1) and not r.escalated
    assert _outputs(db, "task_plan")[0].payload == PLAN
    assert [i["assignee_kind"] for i in _outputs(db, "team_proposal")[0].payload["items"]] == ["ai_agent", "human"]
    c = _reload(db, case)
    assert c.status == "planning" and db.query(Task).count() == 0  # 既存の tasks にはまだ書かない（WP-018）
    run = db.get(AgentRun, r.run_id)
    assert run.status == "done" and run.iterations == 5  # 分解・保存・編成・保存・終了
    children = db.query(AgentRun).filter(AgentRun.parent_run_id == run.id).all()
    assert sorted(x.agent_id for x in children) == ["AG-002", "AG-003"]
    tools_used = [t.tool_id for t in db.query(AgentToolCall).filter(AgentToolCall.run_id == run.id)]
    assert tools_used == ["TOOL-004", "TOOL-005"]


def test_ag001_context_has_no_policy_candidates_or_requirement(db, case, monkeypatch):
    seen = []
    original = llm.call_structured

    def spy(**kw):
        if kw["agent_id"] == "AG-001":
            seen.append(kw["contents"])
        return original(**kw)

    monkeypatch.setattr(llm, "call_structured", spy)
    run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    joined = "\n".join(seen)
    assert "予約サイトと店舗写真" not in joined  # AG-001 は依頼文の原文を受け取らない（context-templates）
    assert "カメラマン" not in joined and "撮影会社" not in joined  # 候補・policy を入れない
    assert "画面設計" in seen[1]  # 委譲先から返ったデータは見せる（PMT-005 で返させるため）


# ---------------------------------------------------------------- DEC-007 (a) の縛り（実行基盤の検証）


def test_wrong_action_is_rejected_and_retried(db, case, monkeypatch):
    real, calls = ag001.expected_step, []

    def step(st):
        calls.append(st.phase)
        return {"action": "delegate_form_team"} if len(calls) == 1 else real(st)  # 最初に順番を飛ばす

    monkeypatch.setattr(ag001, "expected_step", step)
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert r.ok and calls[:2] == ["start", "start"]
    assert db.query(AgentRun).filter(AgentRun.agent_id == "AG-003").count() == 1  # 飛ばした操作は実行されていない


def test_tampered_echo_is_rejected_and_original_is_saved(db, case, monkeypatch):
    real, tampered = ag001.expected_step, []

    def step(st):
        s = real(st)
        if "team_proposal" in s and not tampered:
            tampered.append(1)
            s["team_proposal"]["items"][0]["amount"] = "1"  # 金額を書き換えて返す
        return s

    monkeypatch.setattr(ag001, "expected_step", step)
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert r.ok and tampered
    assert _outputs(db, "team_proposal")[0].payload["items"][0]["amount"] == "400000"  # 保存は手元の出力
    run = db.get(AgentRun, r.run_id)
    assert run.iterations == 6 and any("team_proposal が委譲先から返ったデータと一致しません" in v for v in run.validation_failures)


def test_three_invalid_steps_escalate_without_the_model(db, case, monkeypatch):
    monkeypatch.setattr(ag001, "expected_step", lambda st: {"action": "finish"})
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert not r.ok and r.escalated and r.reason == "orchestrator"
    assert _reload(db, case).status == "planning_failed"
    assert db.query(AgentRun).filter(AgentRun.agent_id.in_(["AG-002", "AG-003"])).count() == 0


# ---------------------------------------------------------------- HIL-005 へ差し戻す 4 つの経路


def test_hil005_when_ag002_fails(db, case):
    bad = {"tasks": [{"seq": 1, "phase": "backend", "title": "x"}]}  # 工程に無い
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(bad), mock_ag003=fixed(TEAM))
    assert not r.ok and r.escalated and r.reason == "violations" and r.plan_revision is None
    c = _reload(db, case)
    assert c.status == "planning_failed" and c.error.startswith("再確認のお願い") and "工程" in c.error
    assert _outputs(db, "task_plan") == [] and _outputs(db, "team_proposal") == []


def test_hil005_when_grd003_is_exceeded(db, case):
    many = {"tasks": [{"seq": i, "phase": "designer", "title": f"t{i}"} for i in range(1, 22)]}
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(many), mock_ag003=fixed(TEAM))
    assert r.escalated and any("上限" in v for v in r.violations)
    assert _reload(db, case).status == "planning_failed"


def test_hil005_when_grd002_fails_three_times(db, case):
    over = {"items": [{"task_seq": 1, "assignee_ens_name": AI, "amount": "900000"}, {"task_seq": 2, "assignee_ens_name": HUMAN, "amount": "900000"}]}
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(over))
    assert r.escalated and r.plan_revision == 1 and r.team_revision is None
    c = _reload(db, case)
    assert c.status == "planning_failed" and "超過額 820000" in c.error
    assert _outputs(db, "team_proposal") == []


def test_hil005_and_operator_log_when_grd005_is_reached(db, case, caplog):
    db.add(AgentRun(agent_id="AG-002", case_id=case.id, status="done", input_tokens=200_000, validation_failures=[], truncations=[]))
    db.commit()
    with caplog.at_level(logging.WARNING):
        r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert r.escalated and r.reason == "limit" and r.limit_hit.kind == "cost_case"
    assert _reload(db, case).status == "planning_failed"
    assert db.get(AgentRun, r.run_id).status == "stopped"
    assert any("GRD-005" in m and "HIL-005" in m for m in caplog.messages)  # 運用者への通知（ログ）


# ---------------------------------------------------------------- 停止・GRD-004


def test_stopped_case_does_nothing(db, case):
    control.stop(db, case_id=case.id, reason="確認", operator="test")
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(PLAN), mock_ag003=fixed(TEAM))
    assert not r.ok and r.reason == "stopped" and not r.escalated
    assert _reload(db, case).status == "planning"  # 停止は差し戻しではない
    assert db.query(AgentRun).filter(AgentRun.agent_id != "AG-001").count() == 0


def _past_request(db, case):
    run = trace.start_run(db, "AG-001", case_id=case.id)
    trace.record_tool_call(db, run, "TOOL-008", allowed=True, ok=True)
    trace.finish_run(db, run, "failed")


def test_grd004_stops_the_case_after_the_limit(db, case):
    for _ in range(3):
        _past_request(db, case)
    bad = {"tasks": [{"seq": 1, "phase": "backend", "title": "x"}]}
    r = run_planning(db, case_id=case.id, mock_ag002=fixed(bad), mock_ag003=fixed(TEAM))
    assert r.case_stopped and not r.ok
    assert control.state(db, case.id).stopped
    c = _reload(db, case)
    assert c.status == "planning_failed" and "上限" in c.error


def test_tool008_is_idempotent_per_case_and_only_for_ag001(db, case):
    run = trace.start_run(db, "AG-001", case_id=case.id)
    first = tools.call_tool(db, run, "TOOL-008", case_id=case.id, reason="violations", violations=["x"])
    again = tools.call_tool(db, run, "TOOL-008", case_id=case.id, reason="violations", violations=["y"])
    assert first.value["requested"] and again.value == {"requested": False, "already_open": True, "case_stopped": False}
    assert _reload(db, case).error == "再確認のお願い（計画の検証に通りませんでした）: x"
    for agent_id in ("AG-002", "AG-003", "AG-004"):
        assert tools.call_tool(db, trace.start_run(db, agent_id, case_id=case.id), "TOOL-008", case_id=case.id, reason="x", violations=[]).denied
