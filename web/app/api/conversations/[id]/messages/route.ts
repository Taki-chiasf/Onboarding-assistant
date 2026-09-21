import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await context.params;
  const res = await fetch(`${backendUrl()}/api/conversations/${id}/messages`, {
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
  return NextResponse.json(await res.json());
}
