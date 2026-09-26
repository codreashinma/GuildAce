from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.proof_store import (
    DuplicateWorldIDProofUse,
    WorldIDProofStoreUnavailable,
)
from app.world_id import WorldIDVerificationError


client = TestClient(main.app)


def make_example_payload() -> dict[str, Any]:
    return {
        "protocol_version": "4.0",
        "nonce": "test-nonce",
        "action": "approve:task-123",
        "environment": "production",
        "responses": [
            {
                "identifier": "proof_of_human",
                "proof": ["0x1"],
                "nullifier": "0x2a",
            }
        ],
    }


def make_verified_result(
    *,
    action: str = "approve:task-123",
    environment: str = "production",
) -> dict[str, str]:
    return {
        "protocol_version": "4.0",
        "action": action,
        "environment": environment,
        "identifier": "proof_of_human",
        "nullifier": "42",
    }


def install_successful_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify_world_proof(
        payload: dict[str, Any],
        *,
        expected_action: str,
        expected_environment: str,
    ) -> dict[str, str]:
        return make_verified_result(
            action=expected_action,
            environment=expected_environment,
        )

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        fake_verify_world_proof,
    )


def test_verify_endpoint_builds_expected_action_and_consumes_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_verify_world_proof(
        payload: dict[str, Any],
        *,
        expected_action: str,
        expected_environment: str,
    ) -> dict[str, str]:
        captured["payload"] = payload
        captured["expected_action"] = expected_action
        captured["expected_environment"] = expected_environment

        return make_verified_result(
            action=expected_action,
            environment=expected_environment,
        )

    def fake_consume_verified_world_id_proof(
        result: dict[str, str],
    ) -> None:
        captured["stored_result"] = result

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        fake_verify_world_proof,
    )
    monkeypatch.setattr(
        main,
        "consume_verified_world_id_proof",
        fake_consume_verified_world_id_proof,
    )

    payload = make_example_payload()
    response = client.post(
        "/world/verify/approve/task-123",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {
        "verified": True,
        "action": "approve:task-123",
    }
    assert response.headers["cache-control"] == "no-store"
    assert captured["payload"] == payload
    assert captured["expected_action"] == "approve:task-123"
    assert captured["expected_environment"] == "production"
    assert captured["stored_result"] == make_verified_result()


def test_verify_endpoint_rejects_duplicate_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_successful_verifier(monkeypatch)

    def duplicate_proof(result: dict[str, str]) -> None:
        raise DuplicateWorldIDProofUse

    monkeypatch.setattr(
        main,
        "consume_verified_world_id_proof",
        duplicate_proof,
    )

    response = client.post(
        "/world/verify/approve/task-123",
        json=make_example_payload(),
    )

    assert response.status_code == 409
    assert response.json() == {
        "verified": False,
        "error": "duplicate_proof",
    }
    assert response.headers["cache-control"] == "no-store"


def test_verify_endpoint_maps_proof_store_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_successful_verifier(monkeypatch)

    def unavailable_store(result: dict[str, str]) -> None:
        raise WorldIDProofStoreUnavailable

    monkeypatch.setattr(
        main,
        "consume_verified_world_id_proof",
        unavailable_store,
    )

    response = client.post(
        "/world/verify/approve/task-123",
        json=make_example_payload(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "verified": False,
        "error": "proof_store_unavailable",
    }
    assert response.headers["cache-control"] == "no-store"


def test_verify_endpoint_rejects_invalid_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def should_not_be_called(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Verifier must not run for an invalid action")

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        should_not_be_called,
    )

    response = client.post(
        "/world/verify/delete/task-123",
        json=make_example_payload(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "verified": False,
        "error": "invalid_action",
    }
    assert response.headers["cache-control"] == "no-store"


def test_verify_endpoint_rejects_invalid_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def should_not_be_called(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Verifier must not run for an invalid scope")

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        should_not_be_called,
    )

    response = client.post(
        "/world/verify/approve/task:123",
        json=make_example_payload(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "verified": False,
        "error": "invalid_scope",
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("content", "headers"),
    [
        (b"", {}),
        (b"{", {"Content-Type": "application/json"}),
        (b"[]", {"Content-Type": "application/json"}),
    ],
)
def test_verify_endpoint_rejects_invalid_request_body(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    headers: dict[str, str],
) -> None:
    async def should_not_be_called(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Verifier must not run for an invalid body")

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        should_not_be_called,
    )

    response = client.post(
        "/world/verify/approve/task-123",
        content=content,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json() == {
        "verified": False,
        "error": "invalid_payload",
    }
    assert response.headers["cache-control"] == "no-store"


def test_verify_endpoint_does_not_store_rejected_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify_world_proof(
        payload: dict[str, Any],
        *,
        expected_action: str,
        expected_environment: str,
    ) -> dict[str, str]:
        raise WorldIDVerificationError(
            "action_mismatch",
            status_code=400,
        )

    def should_not_store(result: dict[str, str]) -> None:
        pytest.fail("Rejected proof must not be stored")

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        fake_verify_world_proof,
    )
    monkeypatch.setattr(
        main,
        "consume_verified_world_id_proof",
        should_not_store,
    )

    response = client.post(
        "/world/verify/approve/task-123",
        json=make_example_payload(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "verified": False,
        "error": "action_mismatch",
    }
    assert response.headers["cache-control"] == "no-store"
