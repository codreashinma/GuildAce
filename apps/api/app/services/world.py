"""World ID 4.0（IDKit v4）連携 — session proof 方式。

World ID 4.0 では uniqueness proof（action 付き）は「1 人につき 1 action 1 回」で、World App 側が 2 回目を拒否する。
このアプリは同じ人が何件でも依頼・承認・レビューを行うので、公式が案内する session proof を使う。

- rp_context: RP 署名鍵で proof リクエストに署名する（@worldcoin/idkit-server の signRequest と同じアルゴリズム）。
  session request は action を持たないので 49 バイトのメッセージに署名する。
- 初回: IDKit `createSession` の結果を Developer Portal の verify API v4 で検証し、返った `session_id` をユーザーに保存する。
- 2 回目以降: 保存済み `session_id` に対する `proveSession` の結果を検証し、`session_id` が一致することを確認する。
- 二重実行防止: (action, signal, session_id) の UNIQUE。proof 単位のリプレイは `session_nullifier` の UNIQUE で防ぐ。
- signal 束縛: 各 response の `signal_hash` が hash_to_field(signal) と一致することを確認する。

WORLD_VERIFY_ENABLED=false の場合はモック（proof を検証せず、ウォレットごとの疑似 session を返す）。"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

from ..config import get_settings

ACTIONS = {"request", "approve", "review", "jury", "human-task"}  # NFR-001 の 5 行為（このアプリ内の二重実行判定キー。World の action ではない）
RP_SIGNATURE_MSG_VERSION = 1
_issued_nonces: dict[str, tuple[str, str, int]] = {}  # rp-context で発行した nonce → (action, signal, expires_at)。再利用・他の操作への流用を拒否する
log = logging.getLogger("choice.world")


@dataclass(frozen=True)
class VerifiedSession:
    session_id: str  # 同じ人間を表す安定した ID（モック時は "mock:..."）
    proof_nullifier: str | None  # この proof 固有の session_nullifier（リプレイ防止）。モック時は None
    created: bool  # このリクエストで新しくセッションが作られた


def _hash_to_field(data: bytes) -> bytes:
    return (int.from_bytes(keccak(data), "big") >> 8).to_bytes(32, "big")


def signal_hash(signal: str) -> str:
    return "0x" + _hash_to_field(signal.encode()).hex()


def sign_request(action: str, signal: str, ttl: int = 300) -> dict:
    """session proof 用の RP 署名（World の action は付けない）を発行する。
    nonce をこのアプリの (action, signal) に紐づけて記録し、検証時に proof が同じ操作向けであることを確認する。"""
    s = get_settings()
    if action not in ACTIONS:
        raise ValueError("unknown action")
    created = int(time.time())
    expires = created + ttl
    nonce = _hash_to_field(os.urandom(32))
    _issued_nonces["0x" + nonce.hex()] = (action, signal, expires)
    for k in [k for k, (_, _, exp) in _issued_nonces.items() if exp < created - 3600]:
        _issued_nonces.pop(k, None)
    if not s.world_rp_signing_key:
        return {
            "rp_id": s.world_rp_id or "rp_mock",
            "nonce": "0x" + nonce.hex(),
            "created_at": created,
            "expires_at": expires,
            "signature": "0x" + "00" * 65,
        }
    msg = bytes([RP_SIGNATURE_MSG_VERSION]) + nonce + created.to_bytes(8, "big") + expires.to_bytes(8, "big")
    signed = Account.sign_message(encode_defunct(msg), private_key=s.world_rp_signing_key)
    return {
        "rp_id": s.world_rp_id,
        "nonce": "0x" + nonce.hex(),
        "created_at": created,
        "expires_at": expires,
        "signature": signed.signature.to_0x_hex(),
    }


def _check_nonce(idkit_response: dict, action: str, signal: str) -> None:
    """proof がこの API がこの操作（action, signal）向けに発行した rp_context に対するものかを確認する。
    ここでは消費しない。検証と記録まで成功した時点で consume_nonce() が消す（途中失敗した proof を同じ rp_context でやり直せるようにするため）。"""
    nonce = idkit_response.get("nonce")
    if not isinstance(nonce, str) or not nonce.startswith("0x") or len(nonce) != 66:
        raise ValueError("World ID の proof に nonce がありません")
    issued = _issued_nonces.get(nonce)
    if issued is None:
        raise ValueError("World ID の rp_context が無効か使用済みです。もう一度お試しください")
    if issued[0] != action or issued[1] != signal:
        raise ValueError("World ID の proof が別の操作向けです（rp_context 不一致）")
    if issued[2] < int(time.time()):
        raise ValueError("World ID の rp_context が期限切れです。もう一度お試しください")


def consume_nonce(idkit_response: dict | None) -> None:
    """検証と記録が完了した proof の rp_context nonce を使用済みにする"""
    if not idkit_response:
        return
    nonce = idkit_response.get("nonce")
    if isinstance(nonce, str):
        _issued_nonces.pop(nonce, None)


def _check_signal(idkit_response: dict, signal: str) -> None:
    """response に signal_hash が入っていれば、この操作の signal と一致することを確認する。
    操作への束縛は nonce（rp_context）で担保しているので、signal_hash が無い場合は通す。"""
    want = signal_hash(signal).lower()
    responses = idkit_response.get("responses")
    if not isinstance(responses, list) or not responses:
        raise ValueError("World ID の proof に responses がありません")
    for r in responses:
        got = r.get("signal_hash") if isinstance(r, dict) else None
        if isinstance(got, str) and got.lower() not in (want, "0x0", "0x"):
            raise ValueError("World ID の proof が別の操作向けです（signal 不一致）")


def _proof_nullifier(idkit_response: dict) -> str:
    """session proof のリプレイ防止キー。responses[].session_nullifier = [nullifier, action] の先頭"""
    for r in idkit_response.get("responses") or []:
        sn = r.get("session_nullifier") if isinstance(r, dict) else None
        if isinstance(sn, list) and sn and isinstance(sn[0], str):
            return sn[0]
    raise ValueError("World ID の proof に session_nullifier がありません")


def redacted(idkit_response: dict | None) -> dict | None:
    """ログ用: proof 本体を除いた形"""
    if not isinstance(idkit_response, dict):
        return idkit_response
    out = {k: v for k, v in idkit_response.items() if k not in ("responses", "integrity_bundle")}
    out["responses"] = [({k: v for k, v in r.items() if k != "proof"} if isinstance(r, dict) else r) for r in (idkit_response.get("responses") or [])]
    return out


def verify_session_proof(*, idkit_response: dict | None, action: str, signal: str, user_wallet: str, saved_session_id: str | None) -> VerifiedSession:
    """session proof を検証する。成功なら VerifiedSession、失敗なら ValueError。
    saved_session_id が None なら createSession の結果（新規）として受け付け、あれば proveSession の結果として一致を要求する。"""
    s = get_settings()
    if not s.world_verify_enabled:
        # モック: 同じウォレットは同じ人間とみなす
        sid = "mock:" + hashlib.sha256(user_wallet.lower().encode()).hexdigest()[:40]
        return VerifiedSession(session_id=sid, proof_nullifier=None, created=saved_session_id is None)
    if not idkit_response:
        raise ValueError("World ID の proof がありません")
    if idkit_response.get("protocol_version") != "4.0":
        raise ValueError("World ID 4.0 の session proof が必要です（旧形式の proof は使えません）")
    session_id = idkit_response.get("session_id")
    if not isinstance(session_id, str) or not session_id.startswith("session_"):
        raise ValueError("World ID の proof に session_id がありません。session proof として確認してください")
    if saved_session_id is not None and session_id != saved_session_id:
        raise ValueError("このアカウントに保存された World セッションと一致しません。同じ World ID で確認してください")
    _check_nonce(idkit_response, action, signal)
    _check_signal(idkit_response, signal)
    proof_nullifier = _proof_nullifier(idkit_response)

    r = httpx.post(f"{s.world_verify_url}/{s.world_rp_id}", json=idkit_response, timeout=30)
    body = None
    try:
        body = r.json()
    except ValueError:
        body = None
    if r.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
        text = (r.text if body is None else str(body))[:300]
        log.warning("world verify rejected (%s): %s / request=%s", r.status_code, text, redacted(idkit_response))
        raise ValueError(f"World ID 検証に失敗しました: {text}")
    if isinstance(body, dict):
        returned = body.get("session_id")
        if isinstance(returned, str) and returned != session_id:
            raise ValueError("World ID 検証結果の session_id が一致しません")
        results = body.get("results")
        if isinstance(results, list) and results and not any(isinstance(x, dict) and x.get("success") for x in results):
            raise ValueError(f"World ID 検証に失敗しました: {str(results)[:300]}")
    return VerifiedSession(session_id=session_id, proof_nullifier=proof_nullifier, created=saved_session_id is None)
