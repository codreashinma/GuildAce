import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user, is_ops, issue_nonce, make_token, verify_siwe
from ..config import get_settings
from ..db import get_db
from ..models import User, WorldVerification
from ..schemas import AuthVerifyIn, MeOut

router = APIRouter(prefix="/auth", tags=["auth"])

# ウォレット接続の前に選ぶ利用者種別。表示とメニューのためのもので、権限は付けない（運用者の権限は OPS_ADDRESSES で決まる）
USER_ROLES = {"client": "発注者", "creator": "Agent 作成者", "worker": "Human Task worker", "jury": "Jury", "ops": "運用者"}


@router.get("/nonce")
def nonce():
    return {"nonce": issue_nonce()}


@router.get("/roles")
def roles():
    return [{"role": k, "label": v} for k, v in USER_ROLES.items()]


@router.post("/verify")
def verify(body: AuthVerifyIn, db: Session = Depends(get_db)):
    if body.role is not None and body.role not in USER_ROLES:
        raise HTTPException(400, "unknown role")
    user, token = verify_siwe(body.message, body.signature, db)
    if body.role is not None and user.role != body.role:
        user.role = body.role
        db.commit()
        db.refresh(user)
    out = MeOut.model_validate(user)
    out.is_ops = is_ops(user)
    return {"token": token, "user": out}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    actions = sorted({v.action for v in db.query(WorldVerification).filter(WorldVerification.user_id == user.id)})
    out = MeOut.model_validate(user)
    out.human_verified_actions = actions
    out.is_ops = is_ops(user)
    return out


# デモアカウント（キー）と、その利用者種別（USER_ROLES のキー）
DEV_USER_ROLES = {"client": "client", "creator": "creator", "worker": "worker", "jury1": "jury", "jury2": "jury", "jury3": "jury", "ops": "ops"}
DEV_USERS = {"client": "発注者", "creator": "Agent 作成者", "worker": "Human Task worker", "jury1": "Jury 1", "jury2": "Jury 2", "jury3": "Jury 3", "ops": "運用者"}


class DevLoginIn(BaseModel):
    role: str


@router.get("/dev-users")
def dev_users():
    if not get_settings().dev_login_enabled:
        return []
    return [{"role": k, "label": v, "type": DEV_USER_ROLES[k]} for k, v in DEV_USERS.items()]


@router.post("/dev-login")
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)):
    """ウォレットなしのデモログイン（DEV_LOGIN_ENABLED=true のときだけ）。役割ごとに固定アドレスのユーザーを使う。"""
    if not get_settings().dev_login_enabled:
        raise HTTPException(404)
    if body.role not in DEV_USERS:
        raise HTTPException(400, "unknown role")
    address = "0x" + hashlib.sha256(f"dev:{body.role}".encode()).hexdigest()[:40]
    user = db.query(User).filter(User.wallet_address == address).one_or_none()
    if user is None:
        user = User(wallet_address=address, display_name=DEV_USERS[body.role], role=DEV_USER_ROLES[body.role])
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.role != DEV_USER_ROLES[body.role]:
        user.role = DEV_USER_ROLES[body.role]
        db.commit()
        db.refresh(user)
    out = MeOut.model_validate(user)
    out.is_ops = is_ops(user)
    return {"token": make_token(user), "user": out}
