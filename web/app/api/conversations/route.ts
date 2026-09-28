import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const res = await fetch(`${backendUrl()}/api/conversations`, {
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
  return NextResponse.json(await res.json());
}

export async function DELETE(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const res = await fetch(`${backendUrl()}/api/conversations`, {
    method: "DELETE",
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  }).catch(() => null);
  if (!res) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
  return NextResponse.json(await res.json(), { status: res.status });
}
