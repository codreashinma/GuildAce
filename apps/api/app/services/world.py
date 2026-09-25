"""World ID（IDKit v4）連携。
- rp_context: RP 署名鍵で proof リクエストに署名する（@worldcoin/idkit-server の signRequest と同じアルゴリズム）
- verify: Developer Portal の verify API v4 で proof を検証し、nullifier を返す
WORLD_VERIFY_ENABLED=false の場合はモック（proof を検証せず、ユーザーごとの疑似 nullifier を返す）。"""

import hashlib
import os
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

from ..config import get_settings

ACTIONS = {"review", "jury", "human-task"}
RP_SIGNATURE_MSG_VERSION = 1


def _hash_to_field(data: bytes) -> bytes:
    return (int.from_bytes(keccak(data), "big") >> 8).to_bytes(32, "big")


def sign_request(action: str, ttl: int = 300) -> dict:
    s = get_settings()
    if action not in ACTIONS:
        raise ValueError("unknown action")
    created = int(time.time())
    expires = created + ttl
    nonce = _hash_to_field(os.urandom(32))
    if not s.world_rp_signing_key:
        return {
            "rp_id": s.world_rp_id or "rp_mock",
            "nonce": "0x" + nonce.hex(),
            "created_at": created,
            "expires_at": expires,
            "signature": "0x" + "00" * 65,
        }
    msg = (
        bytes([RP_SIGNATURE_MSG_VERSION])
        + nonce
        + created.to_bytes(8, "big")
        + expires.to_bytes(8, "big")
        + _hash_to_field(action.encode())
    )
    signed = Account.sign_message(encode_defunct(msg), private_key=s.world_rp_signing_key)
    return {
        "rp_id": s.world_rp_id,
        "nonce": "0x" + nonce.hex(),
        "created_at": created,
        "expires_at": expires,
        "signature": signed.signature.to_0x_hex(),
    }


def _extract_nullifier(obj) -> str | None:
    if isinstance(obj, dict):
        for k in ("nullifier", "nullifier_hash"):
            if isinstance(obj.get(k), str):
                return obj[k]
        for v in obj.values():
            n = _extract_nullifier(v)
            if n:
                return n
    if isinstance(obj, list):
        for v in obj:
            n = _extract_nullifier(v)
            if n:
                return n
    return None


def verify_proof(*, idkit_response: dict | None, action: str, signal: str, user_wallet: str) -> str:
    """検証に成功したら nullifier を返す。失敗なら ValueError。"""
    s = get_settings()
    if action not in ACTIONS:
        raise ValueError("unknown action")
    if not s.world_verify_enabled:
        # モック: 同じウォレットは同じ人間とみなす
        return "mock:" + hashlib.sha256(f"{user_wallet}:{action}".encode()).hexdigest()[:40]
    if not idkit_response:
        raise ValueError("World ID の proof がありません")
    if idkit_response.get("action") not in (None, action):
        raise ValueError("action が一致しません")
    r = httpx.post(f"{s.world_verify_url}/{s.world_rp_id}", json=idkit_response, timeout=30)
    if r.status_code >= 400:
        raise ValueError(f"World ID 検証に失敗しました: {r.text[:300]}")
    body = r.json()
    if body.get("success") is False or body.get("verified") is False:
        raise ValueError(f"World ID 検証に失敗しました: {body}")
    nullifier = _extract_nullifier(body) or _extract_nullifier(idkit_response)
    if not nullifier:
        raise ValueError("nullifier を取得できませんでした")
    return nullifier
