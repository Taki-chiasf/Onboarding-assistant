import { redirect } from "next/navigation";

import { CostDashboard } from "@/components/cost-dashboard";
import { getPrincipal } from "@/lib/auth";

export default async function AdminPage() {
  const principal = await getPrincipal();
  if (!principal) {
    redirect("/login");
  }
  if (principal.role !== "admin") {
    redirect("/");
  }
  return <CostDashboard principal={principal} />;
}
