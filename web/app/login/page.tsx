import { PersonaPicker } from "@/components/persona-picker";
import { SsoLogin } from "@/components/sso-login";
import { getAuthMode } from "@/lib/auth";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { mode } = await getAuthMode();
  if (mode === "oidc") {
    const { error } = await searchParams;
    return <SsoLogin error={error} />;
  }
  return <PersonaPicker />;
}
