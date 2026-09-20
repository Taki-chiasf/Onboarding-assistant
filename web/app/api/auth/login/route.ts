import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

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

  const setCookie = res.headers.get("set-cookie");
  if (setCookie) {
    const [pair] = setCookie.split(";");
    const [name, value] = pair.split("=");
    response.cookies.set(name, value, { httpOnly: true, sameSite: "lax", path: "/" });
  }

  return response;
}
