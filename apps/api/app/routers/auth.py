from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import current_user, issue_nonce, verify_siwe
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
