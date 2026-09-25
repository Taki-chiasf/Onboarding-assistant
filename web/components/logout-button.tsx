"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const router = useRouter();

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <Button
      variant="ghost"
      size={compact ? "icon" : "sm"}
      aria-label="Sign out"
      onClick={logout}
      className="text-muted-foreground hover:text-foreground"
    >
      <LogOut className={compact ? "h-4 w-4" : "h-3.5 w-3.5"} />
      {!compact && "Sign out"}
    </Button>
  );
}
