import { createHash, randomBytes } from "crypto";
import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/backend";

type OidcPublicConfig = {
  authorize_url: string;
  client_id: string;
  audience: string;
  scope: string;
};

const PKCE_COOKIE_MAX_AGE = 600;

export async function GET(request: NextRequest) {
  const modeRes = await fetch(`${backendUrl()}/auth/mode`, { cache: "no-store" }).catch(() => null);
  const mode = modeRes?.ok ? ((await modeRes.json()) as { oidc: OidcPublicConfig | null }) : null;
  if (!mode?.oidc) {
    return NextResponse.redirect(
      new URL("/login?error=oidc_unavailable", request.nextUrl.origin),
    );
  }

  const state = randomBytes(16).toString("base64url");
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");

  const params = new URLSearchParams({
    response_type: "code",
    client_id: mode.oidc.client_id,
    redirect_uri: `${request.nextUrl.origin}/api/auth/oidc/callback`,
    scope: mode.oidc.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  if (mode.oidc.audience) {
    params.set("audience", mode.oidc.audience);
  }

  const response = NextResponse.redirect(`${mode.oidc.authorize_url}?${params.toString()}`);
  const cookieOptions = {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    maxAge: PKCE_COOKIE_MAX_AGE,
  };
  response.cookies.set("oidc_state", state, cookieOptions);
  response.cookies.set("oidc_verifier", verifier, cookieOptions);
  return response;
}
