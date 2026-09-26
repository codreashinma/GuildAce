import { NextResponse } from "next/server";

export const runtime = "nodejs";

const DEMO_ACTION = "approve";
const DEMO_SCOPE = "submission-replay-demo-001";

function noStoreJson(
  content: Record<string, unknown>,
  status: number,
): NextResponse {
  const response = NextResponse.json(content, { status });
  response.headers.set("Cache-Control", "no-store");
  return response;
}

function isJsonObject(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

export async function POST(request: Request): Promise<Response> {
  const backendUrl = process.env.WORLD_BACKEND_URL;

  if (!backendUrl) {
    return noStoreJson(
      {
        verified: false,
        error: "backend_not_configured",
      },
      503,
    );
  }

  let payload: unknown;

  try {
    payload = await request.json();
  } catch {
    return noStoreJson(
      {
        verified: false,
        error: "invalid_json",
      },
      400,
    );
  }

  if (!isJsonObject(payload)) {
    return noStoreJson(
      {
        verified: false,
        error: "invalid_payload",
      },
      400,
    );
  }

  try {
    const endpoint = new URL(
      `/world/verify/${encodeURIComponent(DEMO_ACTION)}/${encodeURIComponent(DEMO_SCOPE)}`,
      backendUrl,
    );

    const backendResponse = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });

    let data: unknown;

    try {
      data = await backendResponse.json();
    } catch {
      return noStoreJson(
        {
          verified: false,
          error: "invalid_backend_response",
        },
        502,
      );
    }

    if (!isJsonObject(data)) {
      return noStoreJson(
        {
          verified: false,
          error: "invalid_backend_response",
        },
        502,
      );
    }

    return noStoreJson(data, backendResponse.status);
  } catch {
    return noStoreJson(
      {
        verified: false,
        error: "backend_unavailable",
      },
      502,
    );
  }
}
