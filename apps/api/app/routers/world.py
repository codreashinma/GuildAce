from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User, WorldVerification
from ..services import world

router = APIRouter(prefix="/world", tags=["world"])


@router.get("/rp-context")
def rp_context(action: str, _: User = Depends(current_user)):
    try:
        return world.sign_request(action)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def verify_and_record(db: Session, user: User, *, action: str, signal: str, idkit_response: dict | None) -> str:
    """proof を検証し nullifier を記録する。同じ人間が同じ signal で二重に検証済みなら 409。"""
    try:
        nullifier = world.verify_proof(idkit_response=idkit_response, action=action, signal=signal, user_wallet=user.wallet_address)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    dup = (
        db.query(WorldVerification)
        .filter(WorldVerification.action == action, WorldVerification.signal == signal, WorldVerification.nullifier == nullifier)
        .one_or_none()
    )
    if dup is not None:
        raise HTTPException(409, "この World ID は既にこの操作を行っています")
    db.add(WorldVerification(user_id=user.id, action=action, signal=signal, nullifier=nullifier))
    db.flush()
    world.consume_nonce(idkit_response)
    return nullifier
