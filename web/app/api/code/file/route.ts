import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

/** Proxy a read-only code file request for the citation viewer. */
export async function GET(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const sourceUri = request.nextUrl.searchParams.get("source_uri");
  if (!sourceUri) {
    return NextResponse.json({ error: "source_uri is required" }, { status: 400 });
  }

  const params = new URLSearchParams({ source_uri: sourceUri });
  for (const key of ["start", "end"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) params.set(key, value);
  }

  const res = await fetch(`${backendUrl()}/api/code/file?${params.toString()}`, {
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
