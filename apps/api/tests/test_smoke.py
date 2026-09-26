"""テストの土台が働いていることの確認（WP-001）。"""

import httpx
import pytest
from google import genai
from web3 import Web3

from app.config import get_settings
from app.models import User
from app.services import gemini
from tests.conftest import TEST_DATABASE_URL, NetworkCallBlocked


def test_settings_use_mocks():
    s = get_settings()
    assert s.database_url == TEST_DATABASE_URL
    assert not s.chain_enabled
    assert not s.gemini_enabled
    assert not s.ens_write_enabled
    assert not s.world_verify_enabled
    assert not s.dev_login_enabled


def test_network_is_blocked():
    with pytest.raises(NetworkCallBlocked):
        httpx.get("https://example.com")


def test_gemini_client_is_blocked():
    with pytest.raises(NetworkCallBlocked):
        genai.Client(api_key="dummy")


def test_web3_rpc_is_blocked():
    with pytest.raises(NetworkCallBlocked):
        Web3(Web3.HTTPProvider("http://127.0.0.1:8545")).eth.block_number


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_db_roundtrip(db):
    db.add(User(wallet_address="0x" + "11" * 20))
    db.commit()
    assert db.query(User).count() == 1


def test_gemini_plan_case_mock_is_deterministic():
    """既存の plan_case は GEMINI_API_KEY が空なら決定的なモックを返す（新しいエージェントのテストもこの方式に合わせる）。"""
    kw = dict(agent_name="PM", agent_rules="", fee_bps=200, title="Web サービス", description="", budget_usdc=3000, deadline=None)
    a, b = gemini.plan_case(**kw), gemini.plan_case(**kw)
    assert a == b
    assert sum(t.estimated_cost for t in a.tasks) <= 3000 * (10_000 - 200) // 10_000
