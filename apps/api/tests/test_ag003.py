"""AG-003 チーム編成（WP-014 / AG-003・TOOL-005・GRD-002・PMT-003/007/011/015・CG-005）。LLM と ENS はモック。"""

import pytest

from app.agents import control, llm, tool_search, tools, trace
from app.agents.ag003_team import form_team
from app.agents.tool_team import TeamProposal, validate_proposal
from app.models import Agent, AgentOutput, AgentRun, Case, Company, Member, User

BUDGET = 1_000_000  # 手数料 2 % を除いた 980,000 が上限
USABLE = 980_000
CREATOR_WALLET = "0x" + "e2" * 20
MEMBER_WALLET = "0x" + "e3" * 20
AI = "design-bot.choice.eth"
HUMAN = "hanako.photo.eth"
TASKS = [{"seq": 1, "phase": "designer", "title": "画面設計"}, {"seq": 2, "phase": "field", "title": "店舗の撮影"}]


@pytest.fixture
def case(db, monkeypatch):
    records = {AI: {"codrea.agent.category": "design"}, HUMAN: {"codrea.person.role": "カメラマン", "codrea.person.company": "photo.eth"}}
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {k: v for k, v in records.get(name, {}).items() if k in (keys or [])})
    client, creator, admin = User(wallet_address="0x" + "e1" * 20), User(wallet_address=CREATOR_WALLET), User(wallet_address="0x" + "e4" * 20)
    db.add_all([client, creator, admin])
    db.flush()
    pm = Agent(creator_id=creator.id, name="PM", label="pm", category="web", payout_address=CREATOR_WALLET, status="draft", fee_bps=200)
    bot = Agent(creator_id=creator.id, name="Design Bot", label="design-bot", category="design", payout_address=CREATOR_WALLET,
                status="published", ens_name=AI, ens_tx_hash="0x" + "ab" * 32, rating_avg=4.5, rating_count=3)
    co = Company(admin_id=admin.id, name="撮影会社", ens_name="photo.eth")
    db.add_all([pm, bot, co])
    db.flush()
    db.add(Member(company_id=co.id, label="hanako", name="花子", wallet_address=MEMBER_WALLET, ens_name=HUMAN, ens_status="written",
                  rating_avg=4.9, completed_count=2))
    c = Case(client_id=client.id, agent_id=pm.id, title="撮影つきサイト", budget=BUDGET, status="planning", escrow_case_id="0x" + "12" * 32)
    db.add(c)
    db.flush()
    trace.save_output(db, "task_plan", c.id, 1, {"tasks": TASKS})
    db.commit()
    return c


def _items(a1="400000", a2="500000", n1=AI, n2=HUMAN):
    return {"items": [{"task_seq": 1, "assignee_ens_name": n1, "amount": a1}, {"task_seq": 2, "assignee_ens_name": n2, "amount": a2}]}


class Seq:
    def __init__(self, *responses):
        self.responses, self.calls, self.n = list(responses), [], 0

    def __call__(self):
        self.n += 1
        return self.responses[min(self.n, len(self.responses)) - 1]


@pytest.fixture
def seen(monkeypatch):
    calls = []
    original = llm.call_structured

    def spy(**kw):
        if isinstance(kw.get("mock"), Seq):
            kw["mock"].calls.append(kw["contents"])
        calls.append(kw)
        return original(**kw)

    monkeypatch.setattr(llm, "call_structured", spy)
    return calls


def _team_outputs(db):
    return db.query(AgentOutput).filter(AgentOutput.kind == "team_proposal").count()


# ---------------------------------------------------------------- 正常・コンテキスト


def test_good_proposal_passes(db, case, seen):
    r = form_team(db, case_id=case.id, mock=Seq(_items()))
    assert r.ok and r.attempts == 1 and r.proposal.model_dump() == _items()
    run = db.get(AgentRun, r.run_id)
    assert (run.agent_id, run.status, run.mode) == ("AG-003", "done", "form_team")


def test_context_has_usable_budget_candidates_and_no_addresses(db, case, seen):
    form_team(db, case_id=case.id, mock=Seq(_items()))
    kw = seen[0]
    assert str(USABLE) in kw["contents"] and str(BUDGET) not in kw["contents"]  # 手数料を除いた額（plan_case と同じ）
    assert AI in kw["contents"] and HUMAN in kw["contents"] and "画面設計" in kw["contents"]
    for secret in (CREATOR_WALLET, MEMBER_WALLET, "花子"):
        assert secret not in kw["contents"] + kw["system"]


def test_default_mock_is_within_budget(db, case):
    r = form_team(db, case_id=case.id)
    assert r.ok and sum(int(i.amount) for i in r.proposal.items) <= USABLE


# ---------------------------------------------------------------- 9-2・GRD-002 の検証


@pytest.mark.parametrize("proposal, word", [
    (_items(n2="stranger.eth"), "候補の一覧にありません"),
    (_items(a1="1.5"), "整数"),
    (_items(a1="-1"), "整数"),
    (_items(a1="1,000"), "整数"),
    ({"items": [{"task_seq": 1, "assignee_ens_name": AI, "amount": "1"}]}, "担当の無いタスク"),
    ({"items": [*_items()["items"], {"task_seq": 2, "assignee_ens_name": AI, "amount": "1"}]}, "2 つ以上"),
    ({"items": [*_items()["items"], {"task_seq": 9, "assignee_ens_name": AI, "amount": "1"}]}, "一覧に無い連番"),
    (_items(a1="500000", a2="480001"), "予算を超えています"),
])
def test_validate_proposal(proposal, word):
    v, _ = validate_proposal(TeamProposal.model_validate(proposal), [1, 2], [AI, HUMAN], USABLE)
    assert any(word in x for x in v)


def test_grd002_excess_is_a_number(db):
    v, excess = validate_proposal(TeamProposal.model_validate(_items(a1="500000", a2="480001")), [1, 2], [AI, HUMAN], USABLE)
    assert excess == 1 and "超過額 1" in v[0]
    assert validate_proposal(TeamProposal.model_validate(_items(a1="490000", a2="490000")), [1, 2], [AI, HUMAN], USABLE) == ([], 0)


# ---------------------------------------------------------------- 再試行（PMT-015・CG-007）


def test_over_budget_is_retried_with_excess_and_fixed(db, case, seen):
    m = Seq(_items(a1="600000", a2="500000"), _items())
    r = form_team(db, case_id=case.id, mock=m)
    assert r.ok and r.attempts == 2
    retry = m.calls[1]
    assert "直前の出力は受理されませんでした" in retry and "超過額 120000" in retry  # 超過額を数値で（PMT-015）
    assert "600000" not in retry  # 前回の出力（金額）を戻さない


def test_over_budget_three_times_fails_and_nothing_is_saved(db, case, seen):
    r = form_team(db, case_id=case.id, mock=Seq(_items(a1="900000", a2="900000")))
    assert not r.ok and r.reason == "violations" and r.attempts == 3 and r.excess == 820_000
    assert len(seen) == 3 and _team_outputs(db) == 0
    assert db.get(AgentRun, r.run_id).status == "failed"


def test_candidate_outside_list_fails_after_retries(db, case, seen):
    r = form_team(db, case_id=case.id, mock=Seq(_items(n1="evil.eth")))
    assert not r.ok and any("候補の一覧" in v for v in r.violations) and _team_outputs(db) == 0


# ---------------------------------------------------------------- 候補 0 件・計画なし・停止


def test_zero_candidates_does_not_call_llm(db, case, seen, monkeypatch):
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {})
    m = Seq(_items())
    r = form_team(db, case_id=case.id, mock=m)
    assert not r.ok and r.reason == "no_candidates" and seen == [] and m.n == 0


def test_no_plan_returns_failure(db, case):
    db.query(AgentOutput).delete()
    db.commit()
    r = form_team(db, case_id=case.id)
    assert not r.ok and r.reason == "no_plan" and r.run_id is None


def test_stopped_case(db, case, seen):
    control.stop(db, case_id=case.id, reason="確認", operator="test")
    r = form_team(db, case_id=case.id, mock=Seq(_items()))
    assert not r.ok and r.reason == "stopped" and seen == []


# ---------------------------------------------------------------- TOOL-005（AG-001 が保存）


def test_tool005_saves_with_kind_decided_by_code(db, case):
    r = form_team(db, case_id=case.id, mock=Seq(_items()))
    ag001 = trace.start_run(db, "AG-001", case_id=case.id)
    for _ in range(2):  # 同じ版は上書き（冪等）
        res = tools.call_tool(db, ag001, "TOOL-005", case_id=case.id, revision=1, items=r.proposal.model_dump()["items"])
        assert res.ok and res.value["total"] == "900000"
    [row] = db.query(AgentOutput).filter(AgentOutput.kind == "team_proposal").all()
    kinds = {i["assignee_ens_name"]: (i["assignee_kind"], i["assignee_user_id"]) for i in row.payload["items"]}
    assert kinds == {AI: ("ai_agent", None), HUMAN: ("human", None)}


@pytest.mark.parametrize("items", [
    _items(a1="500000", a2="480001")["items"],  # GRD-002: 予算超過
    _items(n1="evil.eth")["items"],
    _items(a1="0.5")["items"],
    [{**_items()["items"][0], "assignee_kind": "human"}, _items()["items"][1]],  # 種類はモデルに決めさせない
])
def test_tool005_rejects_invalid_or_over_budget(db, case, items):
    ag001 = trace.start_run(db, "AG-001", case_id=case.id)
    res = tools.call_tool(db, ag001, "TOOL-005", case_id=case.id, revision=1, items=items)
    assert not res.ok and _team_outputs(db) == 0


def test_ag003_cannot_call_tool005(db, case):
    run = trace.start_run(db, "AG-003", case_id=case.id)
    assert tools.call_tool(db, run, "TOOL-005", case_id=case.id, revision=1, items=_items()["items"]).denied
    assert _team_outputs(db) == 0


def test_pm_subagents_only_on_ens_form_team_and_save(db, monkeypatch):
    """DB に候補が無く、PM Agent 配下の専門エージェントが ENS にだけある（発注者自身の PM Agent）→ 候補になり、ai_agent で保存される"""
    parent = "mine.mega.eth"
    subs = {f"{r}.{parent}": {"codrea.agent.role": r, "codrea.agent.parent": parent, "codrea.agent.kind": "ai"} for r in ("designer", "qa")}
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {})
    monkeypatch.setattr(tool_search.ens, "read_texts_many", lambda items, ttl=60.0: {n: dict(subs.get(n, {})) for n, _ in items})
    client = User(wallet_address="0x" + "f1" * 20)
    db.add(client)
    db.flush()
    pm = Agent(creator_id=client.id, name="PM", label="mine", category="web", payout_address=client.wallet_address, status="published",
               owner_mode="creator", parent_ens_name="mega.eth", ens_name=parent, ens_tx_hash="0x" + "ab" * 32, ens_subregistry="0x" + "9" * 40)
    db.add(pm)
    db.flush()
    c = Case(client_id=client.id, agent_id=pm.id, title="自分の PM", budget=BUDGET, status="planning", escrow_case_id="0x" + "13" * 32)
    db.add(c)
    db.flush()
    trace.save_output(db, "task_plan", c.id, 1, {"tasks": TASKS})
    db.commit()
    r = form_team(db, case_id=c.id)  # 既定のモック: 候補を順に割り当てる
    assert r.ok, r.violations
    ag001 = trace.start_run(db, "AG-001", case_id=c.id)
    res = tools.call_tool(db, ag001, "TOOL-005", case_id=c.id, revision=1, items=r.proposal.model_dump()["items"])
    assert res.ok, res.error
    [row] = db.query(AgentOutput).filter(AgentOutput.kind == "team_proposal").all()
    assert {i["assignee_ens_name"]: i["assignee_kind"] for i in row.payload["items"]} == {f"designer.{parent}": "ai_agent", f"qa.{parent}": "ai_agent"}
