import { NextRequest } from "next/server";

import { proxyAdmin } from "@/lib/admin";

export async function GET(request: NextRequest) {
  return proxyAdmin(request, "/api/admin/ingest");
}
