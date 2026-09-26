import { NextRequest, NextResponse } from "next/server";

import { backendUrl, copySessionCookie } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();

  const res = await fetch(`${backendUrl()}/auth/dev/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    return NextResponse.json({ error: "login failed" }, { status: res.status });
  }

  const principal = await res.json();
  const response = NextResponse.json(principal);
  copySessionCookie(res, response);
  return response;
}
