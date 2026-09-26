"""ウォレット接続の前に選んだ利用者種別を、SIWE ログインで保存する（/auth/verify の role）"""

import secrets
from datetime import UTC, datetime

from eth_account import Account
from eth_account.messages import encode_defunct


def _siwe(client, acct, role=None):
    nonce = client.get("/auth/nonce").json()["nonce"]
    issued = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    message = (
        f"localhost:3000 wants you to sign in with your Ethereum account:\n{acct.address}\n\n"
        f"Sign in to Choice\n\nURI: http://localhost:3000\nVersion: 1\nChain ID: 11155111\n"
        f"Nonce: {nonce}\nIssued At: {issued}"
    )
    sig = acct.sign_message(encode_defunct(text=message)).signature.to_0x_hex()
    body = {"message": message, "signature": sig}
    if role is not None:
        body["role"] = role
    return client.post("/auth/verify", json=body)


def test_roles_are_listed(client):
    roles = {r["role"] for r in client.get("/auth/roles").json()}
    assert roles == {"client", "creator", "worker", "jury", "ops"}


def test_verify_saves_role_and_overwrites_on_next_login(client):
    acct = Account.from_key("0x" + secrets.token_hex(32))
    r = _siwe(client, acct, "client")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "client"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me["role"] == "client"
    assert me["is_ops"] is False  # 種別を選んでも権限は付かない

    r = _siwe(client, acct, "jury")
    assert r.json()["user"]["role"] == "jury"
    # 種別を送らないログインは前回の種別を残す
    r = _siwe(client, acct)
    assert r.json()["user"]["role"] == "jury"


def test_verify_rejects_unknown_role_before_consuming_nonce(client):
    acct = Account.from_key("0x" + secrets.token_hex(32))
    assert _siwe(client, acct, "admin").status_code == 400
