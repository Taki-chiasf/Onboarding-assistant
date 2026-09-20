import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function GET() {
  const res = await fetch(`${backendUrl()}/auth/dev/personas`, { cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: "unavailable" }, { status: 502 });
  }
  return NextResponse.json(await res.json());
}
