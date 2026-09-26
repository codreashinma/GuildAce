"""切り替え: 依頼の計画を AG-001 経由に（WP-018 / HIL-002・AG-001〜003・agent-orchestration 13-1）。
LLM・ENS・チェーン・World はモック。/cases の依頼 → ランナー → apply_plan → awaiting_approval → openCase → 預託 → 実行 → 承認まで。"""

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from app.agents import ag001_orchestrator, apply_plan, runner, tool_search, trace
from app.auth import make_token
from app.config import get_settings
from app.models import Agent, AgentOutput, AgentRun, Case, Company, HumanTask, Member, Task, User
from app.services import chain, worker
from app.services.gemini import USDC

AI = "design-bot.choice.eth"
HUMAN = "hanako.photo.eth"
AI_ONLY = {"version": 1, "domain": "web", "workflow": {"phases": [{"key": "designer", "title": "デザイン"}, {"key": "frontend", "title": "実装"}]},
           "human_roles": []}
MIXED = {"version": 1, "domain": "web", "workflow": {"phases": [{"key": "designer", "title": "デザイン"}, {"key": "field", "title": "撮影"}]},
         "human_roles": []}


def _headers(user):
    return {"Authorization": f"Bearer {make_token(user)}"}


def _setup(db, monkeypatch, policy, with_member):
    records = {AI: {"codrea.agent.category": "design"}, HUMAN: {"codrea.person.role": "カメラマン", "codrea.person.company": "photo.eth"}}
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {k: v for k, v in records.get(name, {}).items() if k in (keys or [])})
    key = Account.create()
    client, creator, admin = User(wallet_address=key.address.lower()), User(wallet_address="0x" + "b8" * 20), User(wallet_address="0x" + "b9" * 20)
    db.add_all([client, creator, admin])
    db.flush()
    pm = Agent(creator_id=creator.id, name="PM", label="pm", category="web", payout_address=creator.wallet_address, status="published",
               fee_bps=200, policy=policy)
    bot = Agent(creator_id=creator.id, name="Bot", label="design-bot", category="design", payout_address=creator.wallet_address,
                status="published", ens_name=AI, ens_tx_hash="0x" + "ab" * 32)
    db.add_all([pm, bot])
    if with_member:
        co = Company(admin_id=admin.id, name="撮影会社", ens_name="photo.eth")
        db.add(co)
        db.flush()
        db.add(Member(company_id=co.id, label="hanako", name="花子", wallet_address="0x" + "bb" * 20, ens_name=HUMAN, ens_status="written"))
    db.commit()
    return client, key, pm


@pytest.fixture
def ai_only(db, monkeypatch):
    return _setup(db, monkeypatch, AI_ONLY, with_member=False)


@pytest.fixture
def mixed(db, monkeypatch):
    return _setup(db, monkeypatch, MIXED, with_member=True)


def _create(client_http, user, pm, budget_usdc=1_000):
    r = client_http.post("/cases", json={"agent_id": pm.id, "title": "撮影つきサイト", "description": "コーポレートサイト", "budget_usdc": budget_usdc},
                         headers=_headers(user))
    assert r.status_code == 201, r.text
    return r.json()


def _run_all(db):
    while runner.process_once(db):
        pass
    db.expire_all()


def _drain_chain(db):
    while worker.process_once(db):
        pass
    db.expire_all()


# ---------------------------------------------------------------- 依頼 → awaiting_approval（新しい経路）


def test_request_goes_through_ag001_to_awaiting_approval(db, client, mixed):
    user, _, pm = mixed
    body = _create(client, user, pm)
    assert body["status"] == "planning"
    case = db.get(Case, body["id"])
    run = db.query(AgentRun).filter_by(agent_id="AG-001", case_id=case.id, mode="plan").one()
    assert run.status == "queued"  # BackgroundTasks ではなく、ランナーへの実行要求
    assert db.query(Task).filter_by(case_id=case.id).count() == 0

    _run_all(db)
    case = db.get(Case, case.id)
    assert case.status == "awaiting_approval" and case.error is None  # HIL-002
    tasks = sorted(case.tasks, key=lambda t: t.order_no)
    assert [(t.order_no, t.role, t.type) for t in tasks] == [(0, "designer", "ai"), (1, "field", "human"), (2, "pm", "ai")]
    assert [t.assignee_name for t in tasks] == ["Bot", "花子", "PM"]  # ENS 名から DB の索引で名前を引く
    assert all(t.escrow_task_id == chain.escrow_task_id(t.id) for t in tasks)
    # 金額はチーム案（TOOL-005 に保存された値）そのまま。PM 管理費は残額（CON-006）で、合計は予算に一致する
    team = trace.latest_output(db, "team_proposal", case.id).payload["items"]
    assert [int(t.estimated_cost) for t in tasks[:2]] == [int(i["amount"]) for i in team]
    assert sum(int(t.estimated_cost) for t in tasks) == 1_000 * USDC
    assert int(tasks[2].estimated_cost) >= 1_000 * USDC * 200 // 10_000
    # 画面の表示（要約・チーム）を保つ
    assert case.plan_json["source"] == "agents"
    assert case.plan_json["team"] == [{"name": "Bot", "role": "designer", "kind": "ai"}, {"name": "花子", "role": "field", "kind": "human"}]
    assert "2 件のタスク" in case.plan_json["summary"] and case.plan_json["task_plan_revision"] == 1
    detail = client.get(f"/cases/{case.id}").json()
    assert detail["plan_json"]["summary"] == case.plan_json["summary"] and len(detail["tasks"]) == 3


def test_hil005_failure_is_planning_failed_and_replan_uses_the_new_pipeline(db, client, mixed, monkeypatch):
    user, _, pm = mixed
    monkeypatch.setattr(get_settings(), "agent_max_tasks_per_case", 1)  # GRD-003: 2 工程 → 2 件で必ず超える
    case_id = _create(client, user, pm)["id"]
    _run_all(db)
    case = db.get(Case, case_id)
    assert case.status == "planning_failed" and case.error  # WP-015 の差し戻し（HIL-005）のまま
    assert db.query(Task).filter_by(case_id=case_id).count() == 0

    monkeypatch.setattr(get_settings(), "agent_max_tasks_per_case", 20)
    r = client.post(f"/cases/{case_id}/replan", headers=_headers(user))
    assert r.status_code == 200 and r.json()["status"] == "planning"
    assert db.query(AgentRun).filter_by(agent_id="AG-001", case_id=case_id, status="queued").count() == 1
    _run_all(db)
    case = db.get(Case, case_id)
    assert case.status == "awaiting_approval" and len(case.tasks) == 3


def test_replan_from_awaiting_approval_replaces_tasks_with_the_new_revision(db, client, mixed):
    user, _, pm = mixed
    case_id = _create(client, user, pm)["id"]
    _run_all(db)
    first = {t.id for t in db.get(Case, case_id).tasks}
    assert client.post(f"/cases/{case_id}/replan", headers=_headers(user)).status_code == 200
    _run_all(db)
    case = db.get(Case, case_id)
    assert case.status == "awaiting_approval"
    assert {t.id for t in case.tasks}.isdisjoint(first) and len(case.tasks) == 3
    assert case.plan_json["task_plan_revision"] == 2 and case.plan_json["team_proposal_revision"] == 2


# ---------------------------------------------------------------- 旧経路に戻せる


def test_legacy_pipeline_can_be_restored(db, client, mixed, monkeypatch):
    user, _, pm = mixed
    monkeypatch.setattr(get_settings(), "agent_pipeline", "legacy")
    case_id = _create(client, user, pm)["id"]
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.status == "awaiting_approval"  # TestClient は BackgroundTasks（_plan_job）を応答のあとに実行する
    assert "source" not in case.plan_json  # 旧 plan_case の結果
    assert db.query(AgentRun).count() == 0  # エージェントは動かない
    assert case.tasks[-1].role == "pm" and sum(int(t.estimated_cost) for t in case.tasks) == 1_000 * USDC


# ---------------------------------------------------------------- apply_plan の検証（書き込みの前に決定的なコードで）


def _planned(db, pm, user):
    case = Case(client_id=user.id, agent_id=pm.id, title="t", budget=1_000 * USDC, status="planning", escrow_case_id="0x" + "17" * 32)
    db.add(case)
    db.commit()
    run = trace.start_run(db, "AG-001", mode="plan", case_id=case.id, input_text=case.title)
    assert ag001_orchestrator.run_planning(db, case_id=case.id, run=run).ok
    return case, run


def test_apply_is_idempotent(db, mixed):
    user, _, pm = mixed
    case, run = _planned(db, pm, user)
    assert apply_plan.apply(db, run) is True
    assert apply_plan.apply(db, run) is False  # もう planning ではない
    assert db.query(Task).filter_by(case_id=case.id).count() == 3


def test_grd002_is_checked_again_before_writing_tasks(db, mixed):
    user, _, pm = mixed
    case, run = _planned(db, pm, user)
    row = db.query(AgentOutput).filter_by(kind="team_proposal", target_id=case.id).one()
    row.payload = {"items": [{**i, "amount": str(10_000 * USDC)} for i in row.payload["items"]]}  # 保存後に書き換えられた
    db.commit()
    assert apply_plan.apply(db, run) is False
    db.refresh(case)
    assert case.status == "planning_failed" and "超過額" in case.error
    assert db.query(Task).filter_by(case_id=case.id).count() == 0


def test_mismatched_plan_and_team_are_not_applied(db, mixed):
    user, _, pm = mixed
    case, run = _planned(db, pm, user)
    row = db.query(AgentOutput).filter_by(kind="team_proposal", target_id=case.id).one()
    row.payload = {"items": row.payload["items"][:1]}
    db.commit()
    assert apply_plan.apply(db, run) is False
    db.refresh(case)
    assert case.status == "planning_failed" and "連番" in case.error


def test_outputs_of_another_run_are_not_used(db, mixed):
    user, _, pm = mixed
    case, _ = _planned(db, pm, user)
    other = trace.start_run(db, "AG-001", mode="plan", case_id=case.id, input_text=case.title)
    assert apply_plan.apply(db, other) is False  # この実行は何も保存していない
    db.refresh(case)
    assert case.status == "planning_failed"


# ---------------------------------------------------------------- opened 以降の既存の流れ（チェーンはモック）


def test_new_pipeline_case_goes_through_open_fund_execute_approve(db, client, ai_only):
    user, key, pm = ai_only
    case_id = _create(client, user, pm)["id"]
    _run_all(db)
    assert db.get(Case, case_id).status == "awaiting_approval"

    r = client.post(f"/cases/{case_id}/opened", json={"tx_hash": "0x" + "cd" * 32}, headers=_headers(user))
    assert r.status_code == 200, r.text  # openCase（モック）→ 工程ごとの預託の投入 → 実行（BackgroundTasks）
    _drain_chain(db)
    case = db.get(Case, case_id)
    assert case.status == "delivered"  # AI タスクはすべて提出済み
    assert all(t.status == "done" and t.chain_status == "submitted" for t in case.tasks)

    for t in case.tasks:
        typed = client.get(f"/cases/{case_id}/tasks/{t.id}/typed-data", headers=_headers(user)).json()
        sig = Account.sign_message(encode_typed_data(full_message=typed), key.key).signature.hex()
        r = client.post(f"/cases/{case_id}/tasks/{t.id}/approve", json={"signature": "0x" + sig.removeprefix("0x")}, headers=_headers(user))
        assert r.status_code == 200, r.text
    _drain_chain(db)
    case = db.get(Case, case_id)
    assert all(t.chain_status == "paid" for t in case.tasks)
    assert case.status == "completed"


def test_new_pipeline_human_task_is_created_on_open(db, client, mixed):
    user, _, pm = mixed
    case_id = _create(client, user, pm)["id"]
    _run_all(db)
    assert client.post(f"/cases/{case_id}/opened", json={"tx_hash": "0x" + "ce" * 32}, headers=_headers(user)).status_code == 200
    db.expire_all()
    human = next(t for t in db.get(Case, case_id).tasks if t.type == "human")
    ht = db.query(HumanTask).filter_by(task_id=human.id).one()
    assert ht.reward == int(human.estimated_cost)  # 既存の _execute_job がそのまま Human Task を作る（DEC-014 (a)）
