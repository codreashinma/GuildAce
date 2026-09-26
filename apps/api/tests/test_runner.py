"""エージェントの実行のランナー（WP-017 / DEC-008 (b)・INF-006・10 章・agent-infra 5 章）。LLM と ENS はモック。"""

import pytest
from sqlalchemy import text

from app import main
from app.agents import ag003_team, control, runner, tool_search, trace
from app.db import engine
from app.models import Agent, AgentOutput, AgentRun, Case, Company, Dispute, Member, Task, User

AI = "design-bot.guildace.eth"
HUMAN = "hanako.photo.eth"
POLICY = {"version": 1, "domain": "web", "workflow": {"phases": [{"key": "designer", "title": "デザイン"}, {"key": "field", "title": "撮影"}]},
          "human_roles": []}


class Crash(BaseException):
    """プロセスが途中で落ちたことの代わり（ランナーの except Exception で捕まえない）。"""


@pytest.fixture
def case(db, monkeypatch):
    records = {AI: {"codrea.agent.category": "design"}, HUMAN: {"codrea.person.role": "カメラマン", "codrea.person.company": "photo.eth"}}
    monkeypatch.setattr(tool_search.ens, "read_texts", lambda name, keys=None, ttl=60.0: {k: v for k, v in records.get(name, {}).items() if k in (keys or [])})
    client, creator, admin = User(wallet_address="0x" + "a7" * 20), User(wallet_address="0x" + "a8" * 20), User(wallet_address="0x" + "a9" * 20)
    db.add_all([client, creator, admin])
    db.flush()
    pm = Agent(creator_id=creator.id, name="PM", label="pm", category="web", payout_address=creator.wallet_address, status="draft",
               fee_bps=200, policy=POLICY)
    bot = Agent(creator_id=creator.id, name="Bot", label="design-bot", category="design", payout_address=creator.wallet_address,
                status="published", ens_name=AI, ens_tx_hash="0x" + "ab" * 32)
    co = Company(admin_id=admin.id, name="撮影会社", ens_name="photo.eth")
    db.add_all([pm, bot, co])
    db.flush()
    db.add(Member(company_id=co.id, label="hanako", name="花子", wallet_address="0x" + "aa" * 20, ens_name=HUMAN, ens_status="written"))
    c = Case(client_id=client.id, agent_id=pm.id, title="撮影つきサイト", budget=1_000_000, status="planning", escrow_case_id="0x" + "16" * 32)
    db.add(c)
    db.commit()
    return c


def _outputs(db, kind, target_id):
    return db.query(AgentOutput).filter_by(kind=kind, target_id=target_id).order_by(AgentOutput.revision).all()


# ---------------------------------------------------------------- 1 案件 1 実行


def test_duplicate_request_is_one_job(db, case):
    first = runner.request_planning(db, case.id)
    assert first is not None and first.status == "queued"
    assert runner.request_planning(db, case.id) is None  # 待ちがあるので入れない
    assert db.query(AgentRun).filter_by(agent_id="AG-001", case_id=case.id).count() == 1


def test_running_job_also_blocks_and_finished_job_does_not(db, case):
    runner.request_planning(db, case.id)
    run = runner.claim_next(db)
    assert run.status == "running"
    assert runner.request_planning(db, case.id) is None  # 実行中も 1 件
    runner.execute(db, run)
    assert db.get(AgentRun, run.id).status == "done"
    assert runner.request_planning(db, case.id) is not None  # 終わったら次を受け付ける


def test_plan_and_dispute_are_separate_scopes(db, case):
    d = Dispute(case_id=case.id, reason="不足", status="open")
    db.add(d)
    db.commit()
    assert runner.request_planning(db, case.id) is not None
    assert runner.request_dispute(db, d.id) is not None
    assert runner.request_dispute(db, d.id) is None


# ---------------------------------------------------------------- 取り出しと実行


def test_process_once_runs_the_oldest_and_saves_outputs(db, case):
    runner.request_planning(db, case.id)
    assert runner.process_once(db) and not runner.process_once(db)
    [run] = db.query(AgentRun).filter_by(agent_id="AG-001").all()
    assert run.status == "done"
    assert [o.revision for o in _outputs(db, "task_plan", case.id)] == [1]
    assert [o.revision for o in _outputs(db, "team_proposal", case.id)] == [1]
    # WP-018: 正常に終わった計画は tasks に写して HIL-002（awaiting_approval）へ（2 工程 + PM 管理費）
    assert db.query(Task).count() == 3
    db.refresh(case)
    assert case.status == "awaiting_approval"


def test_stopped_case_is_not_taken_until_resumed(db, case):
    runner.request_planning(db, case.id)
    control.stop(db, case_id=case.id, reason="確認", operator="test")
    assert not runner.process_once(db)
    assert db.query(AgentRun).filter_by(agent_id="AG-001").one().status == "queued"
    control.resume(db, case_id=case.id, reason="確認済み", operator="test")
    assert runner.process_once(db)
    assert db.query(AgentRun).filter_by(agent_id="AG-001").one().status == "done"


def test_exception_marks_failed_and_next_job_continues(db, case, monkeypatch):
    def broken(db, **kw):
        raise RuntimeError("壊れた")

    monkeypatch.setattr(runner.ag001_orchestrator, "run_planning", broken)
    runner.request_planning(db, case.id)
    assert runner.process_once(db)
    run = db.query(AgentRun).filter_by(agent_id="AG-001").one()
    assert run.status == "failed" and "RuntimeError" in run.error


# ---------------------------------------------------------------- 中断と再開（完了条件）


def test_interrupted_run_resumes_to_the_same_revisions(db, case, monkeypatch):
    original = ag003_team.form_team

    def crash(*a, **kw):
        raise Crash()

    monkeypatch.setattr(ag003_team, "form_team", crash)
    runner.request_planning(db, case.id)
    with pytest.raises(Crash):
        runner.process_once(db)  # 計画を保存したあと、編成の途中で落ちる
    db.rollback()
    run = db.query(AgentRun).filter_by(agent_id="AG-001").one()
    assert run.status == "running" and [o.revision for o in _outputs(db, "task_plan", case.id)] == [1]

    assert runner.recover_stale(db) == 1  # 起動時の回復
    db.expire_all()
    assert db.get(AgentRun, run.id).status == "queued"

    monkeypatch.setattr(ag003_team, "form_team", original)
    assert runner.process_once(db)
    db.expire_all()
    assert db.get(AgentRun, run.id).status == "done"
    assert [o.revision for o in _outputs(db, "task_plan", case.id)] == [1]  # 版は増えない（同じ版へ上書き）
    assert [o.revision for o in _outputs(db, "team_proposal", case.id)] == [1]
    assert all(o.run_id == run.id for o in _outputs(db, "task_plan", case.id) + _outputs(db, "team_proposal", case.id))


def test_recover_marks_interrupted_delegate_runs_failed(db, case):
    child = trace.start_run(db, "AG-002", mode="decompose", case_id=case.id)
    assert runner.recover_stale(db) == 0
    db.expire_all()
    assert db.get(AgentRun, child.id).status == "failed"


def test_dispute_job_runs(db, case):
    d = Dispute(case_id=case.id, reason="不足", status="open")
    db.add(d)
    db.commit()
    runner.request_dispute(db, d.id)
    assert runner.process_once(db)
    run = db.query(AgentRun).filter_by(agent_id="AG-001", mode="analyze_dispute").one()
    assert run.status == "done" and run.dispute_id == d.id


# ---------------------------------------------------------------- 既存の DB への索引の追加


def test_migrate_adds_unique_index_idempotently(db):
    db.close()
    with engine.begin() as conn:
        conn.execute(text("drop index if exists uq_agent_runs_one_active"))
    main._migrate()
    main._migrate()
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text("select indexname from pg_indexes where tablename = 'agent_runs'"))]
    assert names.count("uq_agent_runs_one_active") == 1
