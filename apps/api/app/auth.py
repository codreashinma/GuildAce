"""SIWE（Sign-In with Ethereum）+ JWT 認証。"""

import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException
from siwe import SiweMessage
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

_nonces: dict[str, float] = {}  # nonce -> expiry (デモ用のインメモリ)


def issue_nonce() -> str:
    now = time.time()
    for k, exp in list(_nonces.items()):
        if exp < now:
            _nonces.pop(k, None)
    n = secrets.token_hex(16)
    _nonces[n] = now + 600
    return n


def verify_siwe(message: str, signature: str, db: Session) -> tuple[User, str]:
    try:
        msg = SiweMessage.from_message(message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid SIWE message: {e}") from e
    if msg.nonce not in _nonces or _nonces[msg.nonce] < time.time():
        raise HTTPException(401, "Invalid nonce")
    try:
        msg.verify(signature)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"Signature verification failed: {e}") from e
    _nonces.pop(msg.nonce, None)
    address = msg.address.lower()
    user = db.query(User).filter(User.wallet_address == address).one_or_none()
    if user is None:
        user = User(wallet_address=address)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user, make_token(user)


def make_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": user.id, "addr": user.wallet_address, "exp": datetime.now(UTC) + timedelta(hours=24)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, "Invalid token") from e
    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(401, "User not found")
    return user


def optional_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User | None:
    if not authorization:
        return None
    try:
        return current_user(authorization, db)
    except HTTPException:
        return None


def is_ops(user: User) -> bool:
    """運用者か。OPS_ADDRESSES に含まれるウォレット。未設定なら DEV_LOGIN_ENABLED のときだけ全員に開放（ローカル確認用）"""
    s = get_settings()
    allow = s.ops_address_list
    if allow:
        return user.wallet_address.lower() in allow
    return s.dev_login_enabled


def ops_user(user: User = Depends(current_user)) -> User:
    if not is_ops(user):
        raise HTTPException(403, "Only operators (OPS_ADDRESSES) can use this")
    return user
