import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function GET() {
  const res = await fetch(`${backendUrl()}/auth/mode`, { cache: "no-store" }).catch(() => null);
  if (!res || !res.ok) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
  return NextResponse.json(await res.json());
}
