import asyncio
import os
from typing import Any

import httpx
import pytest

os.environ["WORLD_ID_RP_ID"] = "rp_test"
os.environ["WORLD_ID_ENVIRONMENT"] = "production"

import app.world_id as world_id
from app.world_id import WorldIDVerificationError, verify_world_proof


EXPECTED_ACTION = "approve:task-123"


def make_valid_payload() -> dict[str, Any]:
    return {
        "protocol_version": "4.0",
        "nonce": "test-nonce",
        "action": EXPECTED_ACTION,
        "environment": "production",
        "responses": [
            {
                "identifier": "proof_of_human",
                "signal_hash": "0x0",
                "proof": ["0x1"],
                "nullifier": "0x0a",
                "issuer_schema_id": 1,
                "expires_at_min": 9999999999,
            }
        ],
    }


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any) -> None:
        self.status_code = status_code
        self.json_data = json_data

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if isinstance(self.json_data, Exception):
            raise self.json_data
        return self.json_data


class FakeAsyncClient:
    response = FakeResponse(200, {})
    error: Exception | None = None
    posted_url: str | None = None
    posted_json: dict[str, Any] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        traceback: Any,
    ) -> None:
        pass

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
    ) -> FakeResponse:
        type(self).posted_url = url
        type(self).posted_json = json

        if type(self).error is not None:
            raise type(self).error

        return type(self).response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeAsyncClient]:
    FakeAsyncClient.response = FakeResponse(200, {})
    FakeAsyncClient.error = None
    FakeAsyncClient.posted_url = None
    FakeAsyncClient.posted_json = None

    monkeypatch.setattr(world_id.httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


def test_accepts_valid_v4_proof_and_normalizes_nullifier(
    fake_client: type[FakeAsyncClient],
) -> None:
    payload = make_valid_payload()

    fake_client.response = FakeResponse(
        200,
        {
            "success": True,
            "action": EXPECTED_ACTION,
            "environment": "production",
            "results": [
                {
                    "identifier": "proof_of_human",
                    "success": True,
                    "nullifier": "0x0a",
                }
            ],
        },
    )

    result = asyncio.run(
        verify_world_proof(
            payload,
            expected_action=EXPECTED_ACTION,
            expected_environment="production",
        )
    )

    assert result == {
        "protocol_version": "4.0",
        "action": EXPECTED_ACTION,
        "environment": "production",
        "identifier": "proof_of_human",
        "nullifier": "10",
    }
    assert fake_client.posted_json is payload
    assert fake_client.posted_url is not None
    assert fake_client.posted_url.startswith(
        "https://developer.world.org/api/v4/verify/"
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("protocol_version", "3.0", "unsupported_protocol_version"),
        ("action", "approve:task-999", "action_mismatch"),
        ("environment", "staging", "environment_mismatch"),
    ],
)
def test_rejects_invalid_context_before_http_request(
    fake_client: type[FakeAsyncClient],
    field: str,
    value: str,
    expected_code: str,
) -> None:
    payload = make_valid_payload()
    payload[field] = value

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                payload,
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == expected_code
    assert fake_client.posted_json is None


def test_rejects_legacy_orb_proof(
    fake_client: type[FakeAsyncClient],
) -> None:
    payload = make_valid_payload()
    payload["responses"][0]["identifier"] = "orb"

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                payload,
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == "unsupported_proof_type"
    assert fake_client.posted_json is None


def test_rejects_multiple_human_proofs(
    fake_client: type[FakeAsyncClient],
) -> None:
    payload = make_valid_payload()
    payload["responses"].append(
        payload["responses"][0].copy()
    )

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                payload,
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == "invalid_payload"
    assert fake_client.posted_json is None


def test_handles_world_rate_limit(
    fake_client: type[FakeAsyncClient],
) -> None:
    fake_client.response = FakeResponse(429, {"error": "rate_limited"})

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                make_valid_payload(),
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == "world_unavailable"
    assert error.value.status_code == 503


def test_handles_invalid_world_json(
    fake_client: type[FakeAsyncClient],
) -> None:
    fake_client.response = FakeResponse(
        200,
        ValueError("invalid JSON"),
    )

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                make_valid_payload(),
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == "invalid_world_response"
    assert error.value.status_code == 502


def test_handles_world_timeout(
    fake_client: type[FakeAsyncClient],
) -> None:
    fake_client.error = httpx.TimeoutException("timed out")

    with pytest.raises(WorldIDVerificationError) as error:
        asyncio.run(
            verify_world_proof(
                make_valid_payload(),
                expected_action=EXPECTED_ACTION,
                expected_environment="production",
            )
        )

    assert error.value.code == "world_timeout"
    assert error.value.status_code == 504
