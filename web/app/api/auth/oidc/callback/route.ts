import { NextRequest, NextResponse } from "next/server";

import { backendUrl, copySessionCookie } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const loginUrl = new URL("/login", request.nextUrl.origin);
  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  const state = params.get("state");
  const expectedState = request.cookies.get("oidc_state")?.value;
  const verifier = request.cookies.get("oidc_verifier")?.value;

  if (
    params.get("error") ||
    !code ||
    !state ||
    !expectedState ||
    state !== expectedState ||
    !verifier
  ) {
    loginUrl.searchParams.set("error", "oidc_failed");
    return NextResponse.redirect(loginUrl);
  }

  const res = await fetch(`${backendUrl()}/auth/oidc/exchange`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      code,
      code_verifier: verifier,
      redirect_uri: `${request.nextUrl.origin}/api/auth/oidc/callback`,
    }),
  }).catch(() => null);

  if (!res || !res.ok) {
    loginUrl.searchParams.set("error", "oidc_failed");
    return NextResponse.redirect(loginUrl);
  }

  const response = NextResponse.redirect(new URL("/", request.nextUrl.origin));
  copySessionCookie(res, response);
  response.cookies.delete("oidc_state");
  response.cookies.delete("oidc_verifier");
  return response;
}
