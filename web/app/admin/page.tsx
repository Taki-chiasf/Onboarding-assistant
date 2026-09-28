import { redirect } from "next/navigation";

import { AdminConsole } from "@/components/admin/admin-console";
import { getPrincipal } from "@/lib/auth";

export default async function AdminPage() {
  const principal = await getPrincipal();
  if (!principal) {
    redirect("/login");
  }
  if (principal.role !== "admin") {
    redirect("/");
  }
  return <AdminConsole principal={principal} />;
}
