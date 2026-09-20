import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const res = await fetch(`${backendUrl()}/auth/dev/me`, {
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "unauthorized" }, { status: res.status });
  }
  return NextResponse.json(await res.json());
}
