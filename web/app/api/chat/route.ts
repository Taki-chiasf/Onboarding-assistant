import { NextRequest } from "next/server";

import { backendUrl } from "@/lib/backend";
import { LIMITS, clientKey, limitedResponse, rateLimit } from "@/lib/ratelimit";

export async function POST(request: NextRequest) {
  const limit = rateLimit(`chat:${clientKey(request)}`, LIMITS.chat.limit, LIMITS.chat.windowMs);
  if (!limit.ok) {
    return limitedResponse(limit.retryAfterS);
  }

  const session = request.cookies.get("session")?.value;
  if (!session) {
    return new Response("unauthorized", { status: 401 });
  }

  let res: Response | null = null;
  try {
    res = await fetch(`${backendUrl()}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie: `session=${session}`,
      },
      body: await request.text(),
      // Cancel the backend turn when the browser side goes away, so a closed
      // tab does not keep a model call running.
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    // AbortError surfaces here when the client disconnected mid-flight; other
    // failures are transport conditions. Either way the stream is over.
    return new Response("backend error", { status: 502 });
  }

  if (!res.ok || !res.body) {
    // Pass the status through so the client can react to it (401 →
    // re-login, 429/503 → retry later); body stays opaque by design.
    return new Response("backend error", { status: res.status });
  }

  return new Response(res.body, {
    status: res.status,
    headers: {
      "content-type": "text/event-stream",
      // SSE must not be cached or re-encoded, and buffering proxies stall
      // the keepalive pings the backend sends during silent gaps.
      "cache-control": "no-store, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
