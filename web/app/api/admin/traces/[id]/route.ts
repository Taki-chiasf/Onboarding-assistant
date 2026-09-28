import { NextRequest } from "next/server";

import { proxyAdmin } from "@/lib/admin";

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyAdmin(request, `/api/admin/traces/${encodeURIComponent(id)}`);
}
