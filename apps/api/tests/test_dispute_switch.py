"""切り替え: 紛争の論点整理を AG-001 経由に（WP-019 / AG-004・HIL-004）。LLM・ENS・チェーン・World はモック。
依頼（新しい経路）→ 預託 → 実行 → 差し戻し（紛争）→ ランナー → apply_dispute → Jury の投票 → resolve ジョブ → resolved まで。"""

import pytest

from app.agents import ag001_orchestrator, ag004_dispute, runner
from app.config import get_settings
from app.models import AgentRun, Case, ChainJob, Dispute, User
from tests.test_plan_switch import AI_ONLY, _create, _drain_chain, _headers, _run_all, _setup


@pytest.fixture
def delivered(db, client, monkeypatch):
    """新しい経路で計画し、openCase・預託・AI タスクの提出まで済んだ案件（delivered）"""
    user, _, pm = _setup(db, monkeypatch, AI_ONLY, with_member=False)
    case_id = _create(client, user, pm)["id"]
    _run_all(db)
    assert client.post(f"/cases/{case_id}/opened", json={"tx_hash": "0x" + "cd" * 32}, headers=_headers(user)).status_code == 200
    _drain_chain(db)
    assert db.get(Case, case_id).status == "delivered"
    return user, case_id


def _open_dispute(client, user, case_id) -> dict:
    r = client.post(f"/cases/{case_id}/dispute", json={"reason": "予約機能が入っていません"}, headers=_headers(user))
    assert r.status_code == 201, r.text
    return r.json()


def _jurors(db, n=3):
    users = [User(wallet_address="0x" + f"{0xc0 + i:02x}" * 20) for i in range(n)]
    db.add_all(users)
    db.commit()
    return users


def _vote_all(client, db, dispute_id, vote="release"):
    for u in _jurors(db):
        r = client.post(f"/disputes/{dispute_id}/vote", json={"vote": vote}, headers=_headers(u))
        assert r.status_code == 200, r.text
    return r.json()


def _resolve_jobs(db, d):
    return db.query(ChainJob).filter(ChainJob.kind == "resolve", ChainJob.idempotency_key.like(f"resolve:%:{d}")).all()


# ---------------------------------------------------------------- 新しい経路で summary_json が入る


def test_dispute_goes_through_ag001_and_summary_json_is_written(db, client, delivered):
    user, case_id = delivered
    d = _open_dispute(client, user, case_id)
    assert d["summary_json"] is None  # BackgroundTasks ではなく、ランナーへの実行要求
    run = db.query(AgentRun).filter_by(agent_id="AG-001", mode="analyze_dispute", dispute_id=d["id"]).one()
    assert run.status == "queued"

    _run_all(db)
    s = client.get(f"/disputes/{d['id']}").json()["summary_json"]
    assert s["source"] == "agents" and s["version"] == 1 and s["no_issues"] is False and s["no_issues_reason"] is None
    [issue] = s["issues"]
    assert set(issue) == {"title", "requester_position", "provider_position", "evidence_refs"}  # AG-004 の出力の形のまま（結論の項目は無い）
    assert all(ref in s["ref_labels"] for ref in issue["evidence_refs"])  # 根拠の参照は画面で名前にできる
    assert s["ref_labels"][issue["evidence_refs"][0]].startswith("Deliverable: ")


def test_votes_resolve_after_summary(db, client, delivered):
    user, case_id = delivered
    d = _open_dispute(client, user, case_id)
    _run_all(db)
    out = _vote_all(client, db, d["id"])
    assert out["status"] == "closed" and out["outcome"] == "release"
    assert out["summary_json"]["source"] == "agents" and out["summary_json"]["resolve_jobs"]  # 論点を残したまま resolve ジョブを足す
    assert len(_resolve_jobs(db, d["id"])) == 3  # 2 工程 + PM 管理費
    _drain_chain(db)
    assert db.get(Case, case_id).status == "resolved"


# ---------------------------------------------------------------- 論点整理が失敗しても投票と裁定は進む（HIL-004 を止めない）


def test_no_issues_still_lets_jury_vote_and_resolve(db, client, delivered, monkeypatch):
    user, case_id = delivered
    bad = {"issues": [{"title": "x", "requester_position": "a", "provider_position": "b", "evidence_refs": ["deliverable:でっちあげ"]}]}
    monkeypatch.setattr(ag004_dispute, "default_mock", lambda record: lambda: bad)  # 検証（記録を参照していること）に通らない
    d = _open_dispute(client, user, case_id)
    _run_all(db)
    s = db.get(Dispute, d["id"]).summary_json
    assert s["no_issues"] is True and s["issues"] == [] and s["version"] is None and s["no_issues_reason"] == "violations"
    out = _vote_all(client, db, d["id"], vote="refund")
    assert out["outcome"] == "refund" and len(_resolve_jobs(db, d["id"])) == 3  # 2 工程 + PM 管理費


def test_exception_in_the_run_is_written_as_no_issues(db, client, delivered, monkeypatch):
    user, case_id = delivered

    def broken(db, **kw):
        raise RuntimeError("壊れた")

    monkeypatch.setattr(ag001_orchestrator, "run_dispute", broken)
    d = _open_dispute(client, user, case_id)
    _run_all(db)
    s = db.get(Dispute, d["id"]).summary_json
    assert s["no_issues"] is True and s["no_issues_reason"] == "error"  # 例外の文面は画面に出さない
    assert db.query(AgentRun).filter_by(dispute_id=d["id"]).one().status == "failed"
    assert _vote_all(client, db, d["id"])["status"] == "closed"


def test_votes_before_the_summary_are_kept(db, client, delivered):
    """整理が終わる前に投票がそろっても、あとから写す論点が resolve_jobs を消さない。"""
    user, case_id = delivered
    d = _open_dispute(client, user, case_id)
    jobs = _vote_all(client, db, d["id"])["summary_json"]["resolve_jobs"]
    _run_all(db)
    s = db.get(Dispute, d["id"]).summary_json
    assert s["resolve_jobs"] == jobs and s["source"] == "agents"


# ---------------------------------------------------------------- 旧経路に戻せる


def test_legacy_pipeline_can_be_restored(db, client, delivered, monkeypatch):
    user, case_id = delivered
    monkeypatch.setattr(get_settings(), "agent_pipeline", "legacy")
    d = _open_dispute(client, user, case_id)
    db.expire_all()
    s = db.get(Dispute, d["id"]).summary_json
    assert "source" not in s and isinstance(s["issues"], list)  # 旧 summarize_dispute の結果（BackgroundTasks）
    assert db.query(AgentRun).filter_by(mode="analyze_dispute").count() == 0
    assert _vote_all(client, db, d["id"])["status"] == "closed"


def test_duplicate_dispute_run_is_not_queued_twice(db, client, delivered):
    user, case_id = delivered
    d = _open_dispute(client, user, case_id)
    assert runner.request_dispute(db, d["id"]) is None  # 1 紛争 1 実行（WP-017）
