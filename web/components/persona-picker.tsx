"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";

import { PixelCursor, PixelMark } from "@/components/pixel-mark";
import { EASE, riseIn, stagger } from "@/lib/motion";

export type Persona = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

function personaLabel(persona: Persona): string {
  if (persona.role === "admin") return "HR admin";
  if (persona.dept === "Engineering") return "Engineering new hire";
  return `${persona.dept} employee`;
}

export function PersonaPicker() {
  const router = useRouter();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/auth/personas")
      .then((res) => {
        if (!res.ok) throw new Error("could not load personas");
        return res.json();
      })
      .then(setPersonas)
      .catch(() => setError("Could not load demo personas."));
  }, []);

  async function select(persona: Persona) {
    setLoading(persona.sub);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(persona),
    });
    if (!res.ok) {
      setError("Sign-in failed. Is the backend reachable?");
      setLoading(null);
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-6 py-16">
      <div
        aria-hidden
        className="ambient-wash pointer-events-none absolute inset-x-0 top-[12vh] h-[26rem]"
      />
      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="relative w-full max-w-[30rem]"
      >
        <motion.div
          variants={riseIn}
          className="flex flex-col items-center text-center"
        >
          <PixelMark className="h-10 w-10" />
          <h1 className="mt-6 text-3xl font-semibold tracking-tight">
            Onboarding Assistant
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">
            Pick a demo identity to explore the assistant.
          </p>
        </motion.div>

        {error && (
          <motion.p
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="mt-8 border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </motion.p>
        )}

        {personas.length > 0 ? (
          <motion.div variants={riseIn} className="mt-12">
            <p className="px-1 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              Demo identities
            </p>
            <motion.div
              initial="hidden"
              animate="visible"
              variants={{
                hidden: {},
                visible: { transition: { staggerChildren: 0.05, delayChildren: 0.3 } },
              }}
              className="mt-3 divide-y border-y"
            >
              {personas.map((persona) => (
                <motion.button
                  key={persona.sub}
                  variants={{
                    hidden: { opacity: 0, y: 8 },
                    visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: EASE } },
                  }}
                  onClick={() => select(persona)}
                  disabled={loading !== null}
                  whileTap={{ scale: 0.99 }}
                  className="group relative flex w-full items-center gap-3 px-1 py-[18px] text-left transition-colors hover:bg-secondary disabled:cursor-default disabled:opacity-55"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-medium">
                      {personaLabel(persona)}
                    </span>
                    <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">
                      {persona.email} · {persona.dept}
                    </span>
                  </span>
                  {loading === persona.sub ? (
                    <span className="flex shrink-0 items-center gap-2">
                      <PixelCursor />
                      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                        Signing in
                      </span>
                    </span>
                  ) : (
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all duration-200 group-hover:text-foreground md:-translate-x-1 md:opacity-0 md:group-hover:translate-x-0 md:group-hover:opacity-100" />
                  )}
                  {loading === persona.sub && (
                    <motion.span
                      aria-hidden
                      className="bg-ramp absolute inset-x-0 bottom-0 h-px origin-left"
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{
                        duration: 1.2,
                        ease: "easeInOut",
                        repeat: Infinity,
                        repeatDelay: 0.2,
                      }}
                    />
                  )}
                </motion.button>
              ))}
            </motion.div>
          </motion.div>
        ) : (
          !error && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: EASE, delay: 0.2 }}
              className="mt-12 flex flex-col items-center gap-3 border-y py-10"
            >
              <PixelCursor />
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                Loading demo identities
              </p>
            </motion.div>
          )
        )}
      </motion.div>
    </div>
  );
}
