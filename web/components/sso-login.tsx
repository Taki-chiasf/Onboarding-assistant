import { ArrowRight } from "lucide-react";

import { PixelMark } from "@/components/pixel-mark";

export function SsoLogin({ error }: { error?: string }) {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-6 py-16">
      <div
        aria-hidden
        className="ambient-wash pointer-events-none absolute inset-x-0 top-[12vh] h-[26rem]"
      />
      <div className="relative w-full max-w-[30rem]">
        <div className="flex flex-col items-center text-center">
          <PixelMark className="h-10 w-10" />
          <h1 className="mt-6 text-3xl font-semibold tracking-tight">Onboarding Assistant</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">
            Sign in with your company account to continue.
          </p>
        </div>

        {error && (
          <p className="mt-8 border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            Sign-in failed. Please try again.
          </p>
        )}

        <a
          href="/api/auth/oidc/login"
          className="group relative mt-12 flex w-full items-center justify-between border-y px-1 py-[18px] text-left transition-colors hover:bg-secondary"
        >
          <span className="text-[15px] font-medium">Sign in with SSO</span>
          <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-foreground" />
        </a>
      </div>
    </div>
  );
}
