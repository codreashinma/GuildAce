"""PM Agent の定義データ（policy）（WP-009 / GRD-006・DEC-002・DEC-003）。"""

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app import main
from app.agents import policy
from app.auth import make_token
from app.db import engine
from app.models import Agent, User

VALID = {
    "version": 1,
    "domain": "web-saas",
    "workflow": {"phases": [{"key": "design", "title": "デザイン"}, {"key": "frontend", "title": "フロント実装"}]},
    "human_roles": [{"role": "approver", "world_verified": True, "min_count": 2}],
}

# GRD-006: ツールの追加・上限の緩和・World 検証の無効化を狙うスキーマ外のキー
ATTACK = {
    **VALID,
    "tools": ["TOOL-009"],
    "limits": {"agent_cost_tokens_per_case": 10**12, "max_tasks": 1000},
    "world_verify": False,
    "workflow": {**VALID["workflow"], "allowed_tools": ["TOOL-009"], "phases": [
        {"key": "design", "title": "デザイン", "tool": "TOOL-009", "budget": 999}]},
    "human_roles": [{"role": "approver", "world_verified": True, "min_count": 2, "skip_world": True}],
}


def _headers(user):
    return {"Authorization": f"Bearer {make_token(user)}"}


@pytest.fixture
def creator(db):
    u = User(wallet_address="0x" + "e1" * 20)
    db.add(u)
    db.commit()
    return u


# ---------------------------------------------------------------- 検証（GRD-006）


def test_valid_policy_is_kept_as_is():
    assert policy.normalize(VALID) == VALID


def test_grd006_keys_outside_schema_are_dropped():
    out = policy.normalize(ATTACK)
    assert set(out) == {"version", "domain", "workflow", "human_roles"}
    assert out["workflow"] == {"phases": [{"key": "design", "title": "デザイン"}]}
    assert out["human_roles"] == [{"role": "approver", "world_verified": True, "min_count": 2}]
    for word in ("TOOL-009", "limits", "world_verify", "skip_world", "budget", "allowed_tools"):
        assert word not in repr(out)


@pytest.mark.parametrize("broken", [
    {**VALID, "workflow": {"phases": []}},  # 工程は 1 件以上
    {**VALID, "workflow": {"phases": [{"key": "qa", "title": "a"}, {"key": "qa", "title": "b"}]}},  # キーの重複
    {**VALID, "workflow": {"phases": [{"key": "Design Phase", "title": "a"}]}},  # ENS の subname にならないキー
    {**VALID, "workflow": {"phases": [{"key": "qa", "title": ""}]}},
    {**VALID, "workflow": {"phases": [{"key": f"p{i}", "title": "a"} for i in range(21)]}},
    {**VALID, "human_roles": [{"role": "admin", "world_verified": True, "min_count": 1}]},  # 役割は 3 種類だけ
    {**VALID, "human_roles": [{"role": "approver", "world_verified": True}]},  # min_count は必須（既定値なし。Q-007）
    {**VALID, "human_roles": [{"role": "approver", "world_verified": True, "min_count": 0}]},
    {**VALID, "version": 2},
    {k: v for k, v in VALID.items() if k != "human_roles"},
    {k: v for k, v in VALID.items() if k != "domain"},
])
def test_invalid_policy_is_rejected(broken):
    with pytest.raises(ValidationError):
        policy.normalize(broken)


# ---------------------------------------------------------------- 既定の policy（DEC-002）


def test_default_policy_uses_existing_role_keys_and_passes_the_schema():
    d = policy.default_policy("web")
    assert [p["key"] for p in d["workflow"]["phases"]] == ["designer", "frontend", "backend", "field", "qa"]
    assert d["domain"] == "web" and d["human_roles"] == []
    assert policy.normalize(d) == d


def test_effective_falls_back_to_default():
    assert policy.effective(None, "design") == policy.default_policy("design")
    assert policy.effective({"version": 1, "broken": True}, "web") == policy.default_policy("web")
    assert policy.effective(VALID, "web") == VALID


# ---------------------------------------------------------------- DB（DEC-003）


def test_migrate_twice_on_old_schema_keeps_existing_rows(db, creator):
    a = Agent(creator_id=creator.id, name="PM", label="pm", category="web", payout_address=creator.wallet_address, rules="自由文")
    db.add(a)
    db.commit()
    db.close()
    with engine.begin() as conn:
        conn.execute(text("alter table agents drop column policy"))  # 列が無い既存の DB を再現
    main._migrate()
    main._migrate()  # 2 回目も壊れない
    with engine.connect() as conn:
        cols = [r[0] for r in conn.execute(text(
            "select column_name from information_schema.columns where table_name = 'agents' and column_name = 'policy'"))]
        row = conn.execute(text("select name, label, rules, policy from agents")).one()
    assert cols == ["policy"]
    assert tuple(row) == ("PM", "pm", "自由文", None)


# ---------------------------------------------------------------- API


def test_create_agent_stores_normalized_policy(client, db, creator):
    r = client.post("/agents", json={"name": "PM", "label": "pm-a", "policy": ATTACK}, headers=_headers(creator))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["policy"] == policy.normalize(ATTACK)
    assert body["effective_policy"] == policy.normalize(ATTACK)
    db.expire_all()
    assert db.get(Agent, body["id"]).policy == policy.normalize(ATTACK)


def test_create_agent_rejects_invalid_policy(client, db, creator):
    r = client.post("/agents", json={"name": "PM", "label": "pm-b", "policy": {**VALID, "workflow": {"phases": []}}},
                    headers=_headers(creator))
    assert r.status_code == 422
    assert db.query(Agent).count() == 0


def test_update_agent_validates_policy_before_saving(client, db, creator):
    aid = client.post("/agents", json={"name": "PM", "label": "pm-c"}, headers=_headers(creator)).json()["id"]
    bad = client.patch(f"/agents/{aid}", json={"policy": {**VALID, "human_roles": [{"role": "root"}]}}, headers=_headers(creator))
    assert bad.status_code == 422
    db.expire_all()
    assert db.get(Agent, aid).policy is None
    ok = client.patch(f"/agents/{aid}", json={"policy": ATTACK}, headers=_headers(creator))
    assert ok.status_code == 200, ok.text
    assert ok.json()["agent"]["policy"] == policy.normalize(ATTACK)
    assert ok.json()["changed_keys"] == []  # policy は ENS の text record に書かない（DEC-002）


def test_existing_agent_without_policy_still_lists(client, db, creator):
    a = Agent(creator_id=creator.id, name="PM", label="pm-d", category="design", payout_address=creator.wallet_address,
              status="published")
    db.add(a)
    db.commit()
    r = client.get("/agents")
    assert r.status_code == 200, r.text
    [item] = [x for x in r.json() if x["id"] == a.id]
    assert item["policy"] is None
    assert item["effective_policy"] == policy.default_policy("design")
