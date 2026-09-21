import { NextRequest } from "next/server";

import { backendUrl } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const session = request.cookies.get("session")?.value;
  if (!session) {
    return new Response("unauthorized", { status: 401 });
  }

  const res = await fetch(`${backendUrl()}/api/chat`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie: `session=${session}`,
    },
    body: await request.text(),
  });

  if (!res.ok || !res.body) {
    return new Response("backend error", { status: 502 });
  }

  return new Response(res.body, {
    status: res.status,
    headers: { "content-type": "text/event-stream" },
  });
}
