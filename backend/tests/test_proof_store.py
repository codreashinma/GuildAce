from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import proof_store
from app.proof_store import (
    DuplicateWorldIDProofUse,
    WorldIDProofStoreUnavailable,
    consume_verified_world_id_proof,
)


def make_verified_result() -> dict[str, str]:
    return {
        "protocol_version": "4.0",
        "action": "approve:task-123",
        "environment": "production",
        "identifier": "proof_of_human",
        "nullifier": "42",
    }


class FakeSession:
    def __init__(
        self,
        *,
        inserted_id: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.inserted_id = inserted_id
        self.error = error
        self.statement: Any = None

    def scalar(self, statement: Any) -> Any:
        self.statement = statement

        if self.error is not None:
            raise self.error

        return self.inserted_id


class FakeTransaction(AbstractContextManager[FakeSession]):
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __enter__(self) -> FakeSession:
        return self.session

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


def install_fake_session(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
) -> None:
    factory = SimpleNamespace(
        begin=lambda: FakeTransaction(session),
    )
    monkeypatch.setattr(proof_store, "SessionLocal", factory)


def test_consumes_verified_proof_with_atomic_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(inserted_id=uuid4())
    install_fake_session(monkeypatch, session)

    consume_verified_world_id_proof(make_verified_result())

    assert session.statement is not None
    compiled = session.statement.compile()
    assert compiled.params["rp_id"] == "rp_test"
    assert compiled.params["environment"] == "production"
    assert compiled.params["action"] == "approve:task-123"
    assert compiled.params["identifier"] == "proof_of_human"
    assert str(compiled.params["nullifier"]) == "42"


def test_rejects_duplicate_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(inserted_id=None)
    install_fake_session(monkeypatch, session)

    with pytest.raises(DuplicateWorldIDProofUse):
        consume_verified_world_id_proof(make_verified_result())


def test_maps_database_error_to_safe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(error=SQLAlchemyError("database failed"))
    install_fake_session(monkeypatch, session)

    with pytest.raises(WorldIDProofStoreUnavailable):
        consume_verified_world_id_proof(make_verified_result())


@pytest.mark.parametrize(
    "nullifier",
    ["", "-1", "1.5", "not-a-number", "1" * 79],
)
def test_rejects_invalid_normalized_nullifier(
    monkeypatch: pytest.MonkeyPatch,
    nullifier: str,
) -> None:
    def should_not_begin() -> None:
        pytest.fail("Invalid nullifier must not reach the database")

    monkeypatch.setattr(
        proof_store,
        "SessionLocal",
        SimpleNamespace(begin=should_not_begin),
    )
    result = make_verified_result()
    result["nullifier"] = nullifier

    with pytest.raises(WorldIDProofStoreUnavailable):
        consume_verified_world_id_proof(result)
