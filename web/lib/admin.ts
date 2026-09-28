import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

/**
 * Proxy an admin request to the backend with the session cookie. The backend
 * enforces the admin role; the BFF only checks that a session exists.
 */
export async function proxyAdmin(
  request: NextRequest,
  path: string,
  init?: { method?: string; body?: string }
): Promise<NextResponse> {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const res = await fetch(`${backendUrl()}${path}${request.nextUrl.search}`, {
    method: init?.method ?? "GET",
    headers: {
      cookie: `session=${session}`,
      ...(init?.body ? { "content-type": "application/json" } : {}),
    },
    body: init?.body,
    cache: "no-store",
  }).catch(() => null);
  if (!res) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }

  const body = await res.text();
  return new NextResponse(body || null, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
