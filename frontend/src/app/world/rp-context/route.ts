import { signRequest } from "@worldcoin/idkit-core/signing";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const ALLOWED_ACTIONS = new Set([
  "request",
  "approve",
  "review",
  "jury",
  "human-task",
]);

const SCOPE_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export async function GET(request: NextRequest) {
  const action = request.nextUrl.searchParams.get("action");
  const scope = request.nextUrl.searchParams.get("scope");

  if (!action || !ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json(
      {
        error: "Invalid action",
        allowed_actions: Array.from(ALLOWED_ACTIONS),
      },
      { status: 400 },
    );
  }

  if (!scope || !SCOPE_PATTERN.test(scope)) {
    return NextResponse.json(
      {
        error: "Invalid scope",
        message:
          "scope must be 1-64 characters using letters, numbers, underscores, or hyphens",
      },
      { status: 400 },
    );
  }

  const rpId = process.env.WORLD_RP_ID;
  const signingKey = process.env.RP_SIGNING_KEY;

  if (!rpId || !signingKey) {
    return NextResponse.json(
      {
        error: "World ID is not configured",
      },
      { status: 503 },
    );
  }

  const worldAction = `${action}:${scope}`;

  try {
    const rpSignature = signRequest({
      action: worldAction,
      signingKeyHex: signingKey,
      ttl: 300,
    });

    const response = NextResponse.json({
      rp_id: rpId,
      action: worldAction,
      nonce: rpSignature.nonce,
      created_at: rpSignature.createdAt,
      expires_at: rpSignature.expiresAt,
      signature: rpSignature.sig,
    });

    response.headers.set("Cache-Control", "no-store");

    return response;
  } catch (error) {
    console.error(
      "Failed to generate RP context:",
      error instanceof Error ? error.message : "Unknown error",
    );

    return NextResponse.json(
      {
        error: "Failed to generate RP context",
      },
      { status: 500 },
    );
  }
}
