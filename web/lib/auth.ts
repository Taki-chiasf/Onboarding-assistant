import { cookies } from "next/headers";

import { backendUrl } from "@/lib/backend";

export type Principal = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

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
