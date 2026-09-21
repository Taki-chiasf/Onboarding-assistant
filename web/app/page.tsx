import { redirect } from "next/navigation";

import { Chat } from "@/components/chat";
import { LogoutButton } from "@/components/logout-button";
import { getPrincipal } from "@/lib/auth";

export default async function HomePage() {
  const principal = await getPrincipal();
  if (!principal) {
    redirect("/login");
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b px-4 py-2">
        <div>
          <span className="text-sm font-semibold">Onboarding Assistant</span>
          <span className="ml-2 text-xs text-muted-foreground">{principal.email}</span>
        </div>
        <LogoutButton />
      </header>
      <div className="min-h-0 flex-1">
        <Chat principal={principal} />
      </div>
    </div>
  );
}
