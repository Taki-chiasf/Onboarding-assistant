import { cookies } from "next/headers";

import { backendUrl } from "@/lib/backend";

export type Principal = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

export type AuthModeKind = "oidc" | "persona" | "static" | "disabled";

export type AuthMode = {
  mode: AuthModeKind;
  oidc: {
    authorize_url: string;
    client_id: string;
    audience: string;
    scope: string;
  } | null;
};

export async function getAuthMode(): Promise<AuthMode> {
  // The demo falls back to the persona picker when the backend cannot answer,
  // so a cold backend never leaves the login page empty.
  const fallback: AuthMode = { mode: "persona", oidc: null };
  try {
    const res = await fetch(`${backendUrl()}/auth/mode`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as AuthMode;
  } catch {
    return fallback;
  }
}

export async function getPrincipal(): Promise<Principal | null> {
  const store = await cookies();
  const session = store.get("session")?.value;
  if (!session) return null;

  const res = await fetch(`${backendUrl()}/auth/dev/me`, {
    headers: { cookie: `session=${session}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as Principal;
}

export async function getBackendHealth(): Promise<{ healthz: boolean; readyz: boolean }> {
  const healthz = await fetch(`${backendUrl()}/healthz`, { cache: "no-store" })
    .then((res) => res.ok)
    .catch(() => false);
  const readyz = await fetch(`${backendUrl()}/readyz`, { cache: "no-store" })
    .then((res) => res.ok)
    .catch(() => false);
  return { healthz, readyz };
}
