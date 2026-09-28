import { NextRequest } from "next/server";

import { proxyAdmin } from "@/lib/admin";

export async function POST(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyAdmin(request, `/api/admin/review/${encodeURIComponent(id)}/promote`, {
    method: "POST",
    body: await request.text(),
  });
}
