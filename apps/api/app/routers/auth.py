from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from fastapi import HTTPException
from pydantic import BaseModel

from ..auth import current_user, issue_nonce, make_token, verify_siwe
from ..config import get_settings
from ..db import get_db
from ..models import User, WorldVerification
from ..schemas import AuthVerifyIn, MeOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/nonce")
def nonce():
    return {"nonce": issue_nonce()}


@router.post("/verify")
def verify(body: AuthVerifyIn, db: Session = Depends(get_db)):
    user, token = verify_siwe(body.message, body.signature, db)
    return {"token": token, "user": MeOut.model_validate(user)}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    actions = sorted({v.action for v in db.query(WorldVerification).filter(WorldVerification.user_id == user.id)})
    out = MeOut.model_validate(user)
    out.human_verified_actions = actions
    return out


DEV_USERS = {"client": "発注者", "creator": "Agent 作成者", "worker": "Human Task worker", "jury1": "Jury 1", "jury2": "Jury 2", "jury3": "Jury 3"}


class DevLoginIn(BaseModel):
    role: str


@router.get("/dev-users")
def dev_users():
    if not get_settings().dev_login_enabled:
        return []
    return [{"role": k, "label": v} for k, v in DEV_USERS.items()]


@router.post("/dev-login")
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)):
    """ウォレットなしのデモログイン（DEV_LOGIN_ENABLED=true のときだけ）。役割ごとに固定アドレスのユーザーを使う。"""
    if not get_settings().dev_login_enabled:
        raise HTTPException(404)
    if body.role not in DEV_USERS:
        raise HTTPException(400, "unknown role")
    import hashlib
    address = "0x" + hashlib.sha256(f"dev:{body.role}".encode()).hexdigest()[:40]
    user = db.query(User).filter(User.wallet_address == address).one_or_none()
    if user is None:
        user = User(wallet_address=address, display_name=DEV_USERS[body.role])
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"token": make_token(user), "user": MeOut.model_validate(user)}
