"""API を叩く小さなクライアント（SIWE ログイン込み）。scripts/ から使う。"""

import secrets
import time
from datetime import UTC, datetime

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct


class Client:
    def __init__(self, base: str, private_key: str | None = None):
        self.base = base.rstrip("/")
        self.acct = Account.from_key(private_key or "0x" + secrets.token_hex(32))
        self.http = httpx.Client(base_url=self.base, timeout=60)
        self.token: str | None = None

    @property
    def address(self) -> str:
        return self.acct.address

    def login(self) -> dict:
        nonce = self.http.get("/auth/nonce").json()["nonce"]
        issued = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        message = (
            f"localhost:3000 wants you to sign in with your Ethereum account:\n{self.address}\n\n"
            f"Sign in to GuildAce\n\nURI: http://localhost:3000\nVersion: 1\nChain ID: 11155111\n"
            f"Nonce: {nonce}\nIssued At: {issued}"
        )
        sig = self.acct.sign_message(encode_defunct(text=message)).signature.to_0x_hex()
        r = self.http.post("/auth/verify", json={"message": message, "signature": sig})
        r.raise_for_status()
        self.token = r.json()["token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        return r.json()["user"]

    def get(self, path: str, **kw):
        r = self.http.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json=None, expect: int | None = None):
        r = self.http.post(path, json=json or {})
        if expect is not None:
            assert r.status_code == expect, f"{path}: expected {expect}, got {r.status_code} {r.text}"
            return r.json() if r.content else None
        r.raise_for_status()
        return r.json()

    def wait(self, path: str, field: str, values: set[str], timeout: float = 60):
        t0 = time.time()
        while time.time() - t0 < timeout:
            d = self.get(path)
            if d[field] in values:
                return d
            time.sleep(0.5)
        raise TimeoutError(f"{path} {field} not in {values} (last={d[field]})")


def sign_typed(client: "Client", typed: dict) -> str:
    from eth_account.messages import encode_typed_data

    return client.acct.sign_message(encode_typed_data(full_message=typed)).signature.to_0x_hex()


def fake_tx() -> str:
    return "0x" + secrets.token_hex(32)
