import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User, WorldVerification
from ..services import world

router = APIRouter(prefix="/world", tags=["world"])
log = logging.getLogger("choice.world")


@router.get("/rp-context")
def rp_context(action: str, signal: str, user: User = Depends(current_user)):
    """この操作（action, signal）向けの session proof 用 RP 署名と、このユーザーに保存済みの World セッション ID を返す。
    session_id が null なら IDKit は createSession、あれば proveSession(session_id) を使う。"""
    try:
        return {"rp_context": world.sign_request(action, signal), "session_id": user.world_session_id}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def verify_and_record(db: Session, user: User, *, action: str, signal: str, idkit_response: dict | None) -> str:
    """session proof を検証し、(action, signal, session_id) を記録する。
    同じ人間（同じ World セッション）が同じ signal で二重に実行していれば 409。戻り値は同じ人間を表す session_id。"""
    if action not in world.ACTIONS:
        raise HTTPException(400, "unknown action")
    try:
        v = world.verify_session_proof(idkit_response=idkit_response, action=action, signal=signal, user_wallet=user.wallet_address, saved_session_id=user.world_session_id)
    except ValueError as e:
        log.warning("world proof rejected: %s / action=%s signal=%s saved_session=%s / proof=%s", e, action, signal, bool(user.world_session_id), world.redacted(idkit_response))
        raise HTTPException(400, str(e)) from e
    if v.proof_nullifier is not None and db.query(WorldVerification).filter(WorldVerification.proof_nullifier == v.proof_nullifier).first() is not None:
        raise HTTPException(400, "この World ID の proof は既に使用されています。もう一度お試しください")
    if v.created:
        # 初回: セッションをこのアカウントに紐づける。別のアカウントが同じセッションを持っていれば拒否する（1 World ID = 1 アカウント）
        other = db.query(User).filter(User.world_session_id == v.session_id, User.id != user.id).first()
        if other is not None:
            raise HTTPException(409, "この World ID は既に別のアカウントに紐づいています")
        user.world_session_id = v.session_id
    dup = (
        db.query(WorldVerification)
        .filter(WorldVerification.action == action, WorldVerification.signal == signal, WorldVerification.nullifier == v.session_id)
        .one_or_none()
    )
    if dup is not None:
        raise HTTPException(409, "この World ID は既にこの操作を行っています")
    db.add(WorldVerification(user_id=user.id, action=action, signal=signal, nullifier=v.session_id, proof_nullifier=v.proof_nullifier))
    db.flush()
    world.consume_nonce(idkit_response)
    return v.session_id
