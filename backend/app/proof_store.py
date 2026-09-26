import re
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import SessionLocal
from app.models import WorldIDProofUse


REPLAY_CONSTRAINT = "uq_world_id_proof_use_replay"


class DuplicateWorldIDProofUse(Exception):
    pass


class WorldIDProofStoreUnavailable(Exception):
    pass


def consume_verified_world_id_proof(
    result: dict[str, str],
) -> None:
    nullifier_text = result.get("nullifier", "")

    if re.fullmatch(r"[0-9]{1,78}", nullifier_text) is None:
        raise WorldIDProofStoreUnavailable

    try:
        environment = result["environment"]
        action = result["action"]
        identifier = result["identifier"]
    except KeyError as error:
        raise WorldIDProofStoreUnavailable from error

    statement = (
        insert(WorldIDProofUse)
        .values(
            id=uuid4(),
            rp_id=settings.world_id_rp_id,
            environment=environment,
            action=action,
            identifier=identifier,
            nullifier=Decimal(nullifier_text),
        )
        .on_conflict_do_nothing(
            constraint=REPLAY_CONSTRAINT,
        )
        .returning(WorldIDProofUse.id)
    )

    try:
        with SessionLocal.begin() as session:
            inserted_id = session.scalar(statement)
    except SQLAlchemyError as error:
        raise WorldIDProofStoreUnavailable from error

    if inserted_id is None:
        raise DuplicateWorldIDProofUse
