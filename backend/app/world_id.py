import re
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.config import settings


WorldEnvironment = Literal["production", "staging", "sandbox"]

VALID_ENVIRONMENTS = {
    "production",
    "staging",
    "sandbox",
}


class WorldIDVerificationError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


async def verify_world_proof(
    payload: dict[str, Any],
    *,
    expected_action: str,
    expected_environment: WorldEnvironment,
) -> dict[str, str]:
    # expected_action must be constructed by trusted backend code.
    # Account binding and nullifier replay protection are handled separately.
    if not isinstance(expected_action, str) or not expected_action:
        raise WorldIDVerificationError("invalid_expected_action", 500)

    if expected_environment not in VALID_ENVIRONMENTS:
        raise WorldIDVerificationError("invalid_server_environment", 500)

    if not isinstance(payload, dict):
        raise WorldIDVerificationError("invalid_payload")

    if payload.get("protocol_version") != "4.0":
        raise WorldIDVerificationError("unsupported_protocol_version")

    if payload.get("action") != expected_action:
        raise WorldIDVerificationError("action_mismatch")

    if payload.get("environment", "production") != expected_environment:
        raise WorldIDVerificationError("environment_mismatch")

    submitted_responses = payload.get("responses")
    if not isinstance(submitted_responses, list) or not submitted_responses:
        raise WorldIDVerificationError("invalid_payload")

    if any(
        not isinstance(item, dict)
        or item.get("identifier") != "proof_of_human"
        for item in submitted_responses
    ):
        raise WorldIDVerificationError("unsupported_proof_type")

    if not settings.world_id_rp_id.startswith("rp_"):
        raise WorldIDVerificationError("invalid_server_configuration", 500)

    rp_id = quote(settings.world_id_rp_id, safe="")
    url = f"https://developer.world.org/api/v4/verify/{rp_id}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise WorldIDVerificationError("world_timeout", 504) from exc
    except httpx.RequestError as exc:
        raise WorldIDVerificationError("world_connection_error", 502) from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise WorldIDVerificationError("world_unavailable", 503)

    if not response.is_success:
        raise WorldIDVerificationError("world_rejected_request")

    try:
        result = response.json()
    except ValueError as exc:
        raise WorldIDVerificationError("invalid_world_response", 502) from exc

    if not isinstance(result, dict):
        raise WorldIDVerificationError("invalid_world_response", 502)

    if result.get("success") is not True:
        raise WorldIDVerificationError("proof_rejected")

    if result.get("environment") != expected_environment:
        raise WorldIDVerificationError("environment_mismatch")

    verified_action = result.get("action")
    if verified_action is not None and verified_action != expected_action:
        raise WorldIDVerificationError("action_mismatch")

    results = result.get("results")
    if not isinstance(results, list):
        raise WorldIDVerificationError("invalid_world_response", 502)

    for item in results:
        if not isinstance(item, dict) or item.get("success") is not True:
            continue

        if item.get("identifier") != "proof_of_human":
            continue

        nullifier = item.get("nullifier")
        if not isinstance(nullifier, str):
            continue

        if re.fullmatch(r"0x[0-9a-fA-F]{1,64}", nullifier) is None:
            continue

        return {
            "protocol_version": "4.0",
            "action": expected_action,
            "environment": expected_environment,
            "identifier": "proof_of_human",
            "nullifier": str(int(nullifier, 16)),
        }

    raise WorldIDVerificationError("human_proof_not_verified")
