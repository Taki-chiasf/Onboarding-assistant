import { redirect } from "next/navigation";

import { Chat } from "@/components/chat";
import { getPrincipal } from "@/lib/auth";

export default async function HomePage() {
  const principal = await getPrincipal();
  if (!principal) {
    redirect("/login");
  }

  return (
    <div className="h-dvh">
      <Chat principal={principal} />
    </div>
  );
}
