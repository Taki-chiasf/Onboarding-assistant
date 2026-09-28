import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const res = await fetch(`${backendUrl()}/api/feedback`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie: `session=${session}`,
    },
    body: await request.text(),
    cache: "no-store",
  }).catch(() => null);
  if (!res) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }

  return NextResponse.json(await res.json(), { status: res.status });
}
