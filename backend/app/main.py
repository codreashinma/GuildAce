import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.proof_store import (
    DuplicateWorldIDProofUse,
    WorldIDProofStoreUnavailable,
    consume_verified_world_id_proof,
)
from app.world_id import WorldIDVerificationError, verify_world_proof


app = FastAPI(title="Codrea World ID Backend")

ALLOWED_ACTIONS = {
    "request",
    "approve",
    "review",
    "jury",
    "human-task",
}

SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def no_store_json(
    content: dict[str, Any],
    *,
    status_code: int = 200,
) -> JSONResponse:
    response = JSONResponse(
        content=content,
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Demo-only endpoint.
# Production approval must authenticate the user, check permissions,
# and save both the approval and proof use in one transaction.
@app.post("/world/verify/{action}/{scope}")
async def verify_world_id(
    action: str,
    scope: str,
    request: Request,
) -> JSONResponse:
    if action not in ALLOWED_ACTIONS:
        return no_store_json(
            {
                "verified": False,
                "error": "invalid_action",
            },
            status_code=400,
        )

    if SCOPE_PATTERN.fullmatch(scope) is None:
        return no_store_json(
            {
                "verified": False,
                "error": "invalid_scope",
            },
            status_code=400,
        )

    try:
        payload = await request.json()
    except (UnicodeDecodeError, ValueError):
        return no_store_json(
            {
                "verified": False,
                "error": "invalid_payload",
            },
            status_code=400,
        )

    if not isinstance(payload, dict):
        return no_store_json(
            {
                "verified": False,
                "error": "invalid_payload",
            },
            status_code=400,
        )

    expected_action = f"{action}:{scope}"

    try:
        result = await verify_world_proof(
            payload,
            expected_action=expected_action,
            expected_environment=settings.world_id_environment,
        )
    except WorldIDVerificationError as error:
        return no_store_json(
            {
                "verified": False,
                "error": error.code,
            },
            status_code=error.status_code,
        )

    try:
        await run_in_threadpool(
            consume_verified_world_id_proof,
            result,
        )
    except DuplicateWorldIDProofUse:
        return no_store_json(
            {
                "verified": False,
                "error": "duplicate_proof",
            },
            status_code=409,
        )
    except WorldIDProofStoreUnavailable:
        return no_store_json(
            {
                "verified": False,
                "error": "proof_store_unavailable",
            },
            status_code=503,
        )

    return no_store_json(
        {
            "verified": True,
            "action": result["action"],
        }
    )
