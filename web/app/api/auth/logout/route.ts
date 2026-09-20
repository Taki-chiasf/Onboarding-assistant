import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (session) {
    await fetch(`${backendUrl()}/auth/dev/logout`, {
      method: "POST",
      headers: { cookie: `session=${session}` },
    }).catch(() => undefined);
  }

  const response = NextResponse.json({ status: "ok" });
  response.cookies.delete("session");
  return response;
}
