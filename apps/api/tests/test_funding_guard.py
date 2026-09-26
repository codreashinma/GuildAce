"""送金のガード（WP-020 / GRD-009・GRD-010・GRD-011・GRD-007・OPS-001 の権限の失効）。チェーンには何も送らない。"""

import importlib.util
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import control, funding_guard
from app.config import get_settings
from app.main import app
from app.models import Agent, Case, ChainJob, FundingGrant, Task, User
from app.services import chain
from app.services.gemini import USDC


def _agent_ops():
    path = Path(__file__).resolve().parent.parent / "scripts" / "agent_ops.py"
    spec = importlib.util.spec_from_file_location("agent_ops", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(db, *, status="in_progress", opened=True, amount=100 * USDC, n=2) -> Case:
    u = User(wallet_address="0x" + f"{db.query(User).count() + 0xd0:02x}" * 20)
    db.add(u)
    db.flush()
    a = Agent(creator_id=u.id, name="PM", label=f"pm{u.id[:6]}", category="web", payout_address=u.wallet_address, status="published")
    db.add(a)
    db.flush()
    c = Case(client_id=u.id, agent_id=a.id, title="t", budget=10_000 * USDC, status=status, escrow_case_id="0x" + "18" * 32,
             open_tx_hash=("0x" + "cd" * 32) if opened else None, plan_json={"summary": "", "team": [], "team_proposal_revision": 1})
    db.add(c)
    db.flush()
    for i in range(n):
        t = Task(case_id=c.id, order_no=i, title=f"t{i}", type="ai", role="designer", estimated_cost=amount)
        db.add(t)
        db.flush()
        t.escrow_task_id = chain.escrow_task_id(t.id)
    db.commit()
    return c


@pytest.fixture
def approved(db):
    """HIL-002 で承諾され（openCase 確認済み・in_progress）、権限が発行された案件"""
    c = _case(db)
    funding_guard.issue(db, c.id)
    return c


def _task(c, i=0) -> Task:
    return c.tasks[i]


def _fund_job(db, task, amount, status="queued", created_at=None):
    j = ChainJob(kind="fund_task", idempotency_key=f"fund:{task.id}", status=status,
                 payload={"task_db_id": task.id, "amount": str(amount)})
    db.add(j)
    db.commit()
    if created_at is not None:
        j.created_at = created_at
        db.commit()
    return j


def _reasons(d):
    return [r.split(":", 1)[0] for r in d.reasons]


# ---------------------------------------------------------------- すべて満たすと受理


def test_all_conditions_met_is_accepted_and_values_come_from_tasks(db, approved):
    t = _task(approved)
    d = funding_guard.check(db, t.id, 1)
    assert d.ok and d.reasons == []
    assert d.order.amount == int(t.estimated_cost)  # GRD-009 (1): 金額は tasks から
    assert (d.order.task_db_id, d.order.case_id_hex, d.order.task_id_hex) == (t.id, approved.escrow_case_id, t.escrow_task_id)


def test_check_does_not_enqueue_or_change_anything(db, approved):
    funding_guard.check(db, _task(approved).id, 1)
    assert db.query(ChainJob).count() == 0  # この WP では送金のジョブを投入しない
    assert _task(approved).chain_status == "none"


# ---------------------------------------------------------------- GRD-009 (1): 金額と送金先を渡す手段が無い


def test_grd009_check_takes_no_amount_or_destination():
    assert list(inspect.signature(funding_guard.check).parameters) == ["db", "task_id", "revision"]


def test_grd009_no_api_route_for_funding():
    """送金の口は公開 API に無い（TOOL-009 は WP-021 でエージェントのツールとして作る）"""
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not [p for p in paths if "fund" in p.lower()]


def test_grd009_revision_must_be_the_approved_team_proposal(db, approved):
    d = funding_guard.check(db, _task(approved).id, 2)
    assert not d.ok and _reasons(d) == ["GRD-009"]
    approved.plan_json = {"summary": ""}  # 承諾した版が無い（旧経路の案件）
    db.commit()
    assert _reasons(funding_guard.check(db, _task(approved).id, 1)) == ["GRD-009"]


def test_unknown_task_is_rejected(db):
    d = funding_guard.check(db, "no-such-task", 1)
    assert not d.ok and _reasons(d) == ["GRD-009"]


# ---------------------------------------------------------------- GRD-009 (2): 1 タスク 1 回・24 時間の上限


def test_grd009_once_per_task_by_projection(db, approved):
    t = _task(approved)
    t.chain_status = "funded"
    db.commit()
    assert _reasons(funding_guard.check(db, t.id, 1)) == ["GRD-009"]


def test_grd009_once_per_task_by_queued_job_but_failed_job_does_not_count(db, approved):
    t = _task(approved)
    j = _fund_job(db, t, t.estimated_cost)
    assert _reasons(funding_guard.check(db, t.id, 1)) == ["GRD-009"]
    j.status = "failed"
    db.commit()
    assert funding_guard.check(db, t.id, 1).ok
    assert funding_guard.check(db, _task(approved, 1).id, 1).ok  # 別のタスクは数えない


def test_grd009_24h_limit(db, approved, monkeypatch):
    monkeypatch.setattr(get_settings(), "funding_limit_24h", 150 * USDC)
    t0, t1 = _task(approved, 0), _task(approved, 1)
    assert funding_guard.check(db, t1.id, 1).ok  # 100 ≤ 150
    _fund_job(db, t0, 100 * USDC)  # 直近 24 時間に 100 を投入済み
    d = funding_guard.check(db, t1.id, 1)
    assert not d.ok and _reasons(d) == ["GRD-009"] and "24 時間" in d.reasons[0]  # 100 + 100 > 150


def test_grd009_24h_window_excludes_older_jobs(db, approved, monkeypatch):
    monkeypatch.setattr(get_settings(), "funding_limit_24h", 150 * USDC)
    other = _case(db)
    _fund_job(db, _task(other), 100 * USDC, created_at=datetime.now(UTC) - timedelta(hours=25))
    assert funding_guard.check(db, _task(approved, 1).id, 1).ok
    assert funding_guard.sent_in_24h(db) == 0


def test_grd009_default_limit_is_20000_usdc():
    assert get_settings().funding_limit_24h == 20_000 * USDC  # DEC-012


# ---------------------------------------------------------------- GRD-011: 承諾の必須


@pytest.mark.parametrize("amount", [1, 1_000_000 * USDC])
@pytest.mark.parametrize("status", ["planning", "planning_failed", "awaiting_approval"])
def test_grd011_unapproved_case_is_rejected_regardless_of_amount(db, status, amount):
    c = _case(db, status=status, opened=False, amount=amount)
    funding_guard.issue(db, c.id)
    d = funding_guard.check(db, _task(c).id, 1)
    assert not d.ok and "GRD-011" in _reasons(d)


def test_grd011_status_without_opencase_is_rejected(db):
    c = _case(db, status="in_progress", opened=False)
    funding_guard.issue(db, c.id)
    assert _reasons(funding_guard.check(db, _task(c).id, 1)) == ["GRD-011"]


# ---------------------------------------------------------------- GRD-010: 権限の失効


def test_grd010_no_grant_is_rejected(db):
    c = _case(db)
    assert _reasons(funding_guard.check(db, _task(c).id, 1)) == ["GRD-010"]


def test_grd010_expired_grant_is_rejected(db, approved):
    g = db.query(FundingGrant).filter_by(case_id=approved.id).one()
    assert (g.expires_at - g.issued_at) == timedelta(days=30)  # DEC-012
    g.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _reasons(funding_guard.check(db, _task(approved).id, 1)) == ["GRD-010"]


@pytest.mark.parametrize("status", ["completed", "resolved"])
def test_grd010_settled_case_is_rejected(db, approved, status):
    approved.status = status
    db.commit()
    assert _reasons(funding_guard.check(db, _task(approved).id, 1)) == ["GRD-010"]


def test_grd010_revoked_grant_is_rejected_and_issue_is_idempotent(db, approved):
    g = funding_guard.issue(db, approved.id)
    assert funding_guard.issue(db, approved.id).id == g.id  # 有効な権限があれば新しく作らない
    assert funding_guard.revoke(db, case_id=approved.id, reason="test") == 1
    assert _reasons(funding_guard.check(db, _task(approved).id, 1)) == ["GRD-010"]


# ---------------------------------------------------------------- GRD-007: 停止中


def test_grd007_global_and_case_stop_are_rejected(db, approved):
    t = _task(approved)
    control.stop(db, case_id=approved.id, reason="調査", operator="test")
    assert "GRD-007" in _reasons(funding_guard.check(db, t.id, 1))
    control.resume(db, case_id=approved.id, reason="済み", operator="test")
    control.stop(db, reason="全体", operator="test")
    assert "GRD-007" in _reasons(funding_guard.check(db, t.id, 1))


# ---------------------------------------------------------------- OPS-001 / OPS-002: 停止と同時に権限を失効


def test_ops001_stop_all_revokes_every_grant_and_resume_does_not_restore(db, approved, capsys):
    other = _case(db)
    funding_guard.issue(db, other.id)
    ops = _agent_ops()
    assert ops.main(["stop-all", "--reason", "原因不明の送金", "--operator", "ops"]) == 0
    assert "送金操作権限を失効  2 件" in capsys.readouterr().out
    assert ops.main(["resume-all", "--operator", "ops"]) == 0
    for c in (approved, other):
        d = funding_guard.check(db, _task(c).id, 1)
        assert _reasons(d) == ["GRD-010"]  # 再開しても権限は戻らない
    assert all(g.revoke_reason.startswith("global の停止") for g in db.query(FundingGrant))


def test_ops002_stop_case_revokes_only_that_case(db, approved, capsys):
    other = _case(db)
    funding_guard.issue(db, other.id)
    assert _agent_ops().main(["stop-case", approved.id, "--reason", "この案件だけ", "--operator", "ops"]) == 0
    assert "送金操作権限を失効  1 件" in capsys.readouterr().out
    assert funding_guard.active_grant(db, approved.id) is None
    assert funding_guard.check(db, _task(other).id, 1).ok
