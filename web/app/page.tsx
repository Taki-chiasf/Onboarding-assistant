import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/logout-button";
import { getBackendHealth, getPrincipal } from "@/lib/auth";

export default async function HomePage() {
  const principal = await getPrincipal();
  if (!principal) {
    redirect("/login");
  }

  const { healthz, readyz } = await getBackendHealth();
  const backendReady = healthz && readyz;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Onboarding Assistant</h1>
          <p className="text-sm text-muted-foreground">Signed in as {principal.email}</p>
        </div>
        <LogoutButton />
      </div>

      <div className="rounded-lg border bg-card p-6">
        <h2 className="font-medium">Your context</h2>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <dt className="text-muted-foreground">Department</dt>
          <dd>{principal.dept}</dd>
          <dt className="text-muted-foreground">Role</dt>
          <dd>{principal.role}</dd>
          <dt className="text-muted-foreground">Subject</dt>
          <dd className="truncate">{principal.sub}</dd>
        </dl>
      </div>

      <div className="mt-4 flex items-center gap-2 text-sm">
        <span className={backendReady ? "text-emerald-600" : "text-amber-600"}>
          {backendReady ? "Backend healthy" : "Backend not ready"}
        </span>
      </div>
    </main>
  );
}
