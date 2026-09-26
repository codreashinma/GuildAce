"""テストの土台（エージェント実装計画 WP-001）。
- テスト用の DB（TEST_DATABASE_URL、既定はローカルの PostgreSQL の choice_test）を使い、接続できなければ DB を使うテストを skip する
- 外部連携の設定をすべて空にしてモックで動かす（.env より環境変数が優先されるので、手元の鍵は使われない）
- Gemini・World・Sepolia への実際の通信を禁止する
アプリ（app.*）は設定を読み込み時に確定させるため、環境変数を設定してから import する（下の E402）。"""

import os
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from google import genai
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from web3 import HTTPProvider

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://choice:choice@localhost:5433/choice_test")
# テストは drop_all でテーブルを消すので、開発・本番の DB を指していたら止める
if not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
    raise RuntimeError(f"TEST_DATABASE_URL のデータベース名は _test で終わる必要があります: {TEST_DATABASE_URL}")

os.environ.update({
    "DATABASE_URL": TEST_DATABASE_URL,
    "JWT_SECRET": "test-secret",
    "CORS_ORIGINS": "http://localhost:3000",
    "DEV_LOGIN_ENABLED": "false",
    # 外部連携はすべてモック
    "SEPOLIA_RPC_URL": "",
    "SERVER_PRIVATE_KEY": "",
    "REPUTATION_PRIVATE_KEY": "",
    "PROJECT_PRIVATE_KEY": "",
    "ESCROW_ADDRESS": "",
    "USDC_ADDRESS": "",
    "ENS_WRITE_ENABLED": "false",
    "ENS_OWNED_RESOLVER": "",
    "ENS_PARENT_SUBREGISTRY": "",
    "ENS_REPUTATION_RESOLVER": "",
    "ENS_PROJECT_RESOLVER": "",
    "WORLD_APP_ID": "",
    "WORLD_RP_ID": "",
    "WORLD_RP_SIGNING_KEY": "",
    "WORLD_VERIFY_ENABLED": "false",
    "GEMINI_API_KEY": "",
})

from app import models  # noqa: E402, F401  テーブル定義を登録する
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


def _ensure_test_database() -> bool:
    """テスト用のデータベースが無ければ作る。サーバーに接続できなければ False。"""
    url = make_url(TEST_DATABASE_URL)
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(text("select 1 from pg_database where datname = :n"), {"n": url.database}).scalar()
            if not exists:
                conn.execute(text(f'create database "{url.database}"'))
        admin.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


DB_AVAILABLE = _ensure_test_database()


class NetworkCallBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """実際の外部通信を禁止する。TestClient は専用のトランスポートを使うので影響しない。"""

    def _deny(*_a, **_k):
        raise NetworkCallBlocked("テスト中に外部への通信が発生しました")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _deny)
    monkeypatch.setattr(HTTPProvider, "make_request", _deny)
    monkeypatch.setattr(genai, "Client", _deny)


@pytest.fixture
def db():
    """テストごとにテーブルを作り直した Session。"""
    if not DB_AVAILABLE:
        pytest.skip(f"テスト用の DB に接続できません: {TEST_DATABASE_URL}")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(db):
    """API の TestClient。起動処理（テーブル作成・マイグレーション・チェーン連携ワーカーの起動）を行わない。"""

    @asynccontextmanager
    async def _no_lifespan(_):
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _no_lifespan
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.router.lifespan_context = original
