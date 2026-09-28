"use client";

import { cn } from "@/lib/utils";

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="px-1 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {title}
      </h2>
      <div className="mt-3 border-y">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-background px-4 py-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold tabular-nums tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Stats({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden border bg-border md:grid-cols-4">
      {children}
    </div>
  );
}

const FLAG_TONES = {
  ok: "border-foreground/20 bg-secondary text-foreground",
  warn: "border-brand-orange/40 bg-brand-orange/10 text-brand-orange",
  error: "border-destructive/25 bg-destructive/5 text-destructive",
  neutral: "border-border bg-secondary text-muted-foreground",
} as const;

export function Flag({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof FLAG_TONES;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]",
        FLAG_TONES[tone]
      )}
    >
      {children}
    </span>
  );
}

export function Empty({ children = "Nothing recorded yet." }: { children?: React.ReactNode }) {
  return <p className="py-6 text-sm text-muted-foreground">{children}</p>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="py-6 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
      {label}
    </p>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      {children}
    </p>
  );
}
