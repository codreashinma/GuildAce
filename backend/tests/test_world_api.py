from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
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


def test_verify_endpoint_builds_expected_action(
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

        return {
            "protocol_version": "4.0",
            "action": expected_action,
            "environment": expected_environment,
            "identifier": "proof_of_human",
            "nullifier": "42",
        }

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        fake_verify_world_proof,
    )

    payload = make_example_payload()
    response = client.post(
        "/world/verify/approve/task-123",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {
        "verified": True,
        "protocol_version": "4.0",
        "action": "approve:task-123",
        "environment": "production",
        "identifier": "proof_of_human",
        "nullifier": "42",
    }
    assert response.headers["cache-control"] == "no-store"
    assert captured["payload"] == payload
    assert captured["expected_action"] == "approve:task-123"
    assert captured["expected_environment"] == "production"


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


def test_verify_endpoint_maps_verification_error(
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

    monkeypatch.setattr(
        main,
        "verify_world_proof",
        fake_verify_world_proof,
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
