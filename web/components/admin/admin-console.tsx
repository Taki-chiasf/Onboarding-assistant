"use client";

import { useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft } from "lucide-react";

import { AttentionPanel } from "@/components/admin/attention-list";
import { CostPanel } from "@/components/admin/cost-dashboard";
import { EvalPanel } from "@/components/admin/eval-dashboard";
import { IngestPanel } from "@/components/admin/ingest-status";
import { ReviewPanel } from "@/components/admin/review-queue";
import { TraceViewer } from "@/components/admin/trace-viewer";
import { LogoutButton } from "@/components/logout-button";
import { PixelMark } from "@/components/pixel-mark";
import { cn } from "@/lib/utils";
import { EASE } from "@/lib/motion";

type Principal = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

const TABS = [
  { id: "cost", label: "Cost", blurb: "Spend, tokens, and the daily budget" },
  { id: "eval", label: "Eval", blurb: "Nightly runs, metrics, and feedback sources" },
  { id: "review", label: "Review", blurb: "Promote or reject filed eval candidates" },
  { id: "ingest", label: "Ingest", blurb: "Index status per source document" },
  { id: "attention", label: "Attention", blurb: "Unanswered and low-confidence questions" },
] as const;

type TabID = (typeof TABS)[number]["id"];

export function AdminConsole({ principal }: { principal: Principal }) {
  const [tab, setTab] = useState<TabID>("cost");
  const [traceId, setTraceId] = useState<string | null>(null);
  const active = TABS.find((entry) => entry.id === tab) ?? TABS[0];

  return (
    <div className="min-h-dvh">
      <div className="mx-auto w-full max-w-5xl px-4 py-10 md:px-6">
        <header className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <PixelMark className="h-6 w-6" assemble={false} />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold tracking-tight">Admin console</h1>
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                {active.blurb}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
              Chat
            </Link>
            <LogoutButton />
          </div>
        </header>

        <nav
          aria-label="Console sections"
          className="mt-8 flex flex-wrap gap-2 border-b pb-3"
        >
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              aria-current={tab === entry.id ? "page" : undefined}
              className={cn(
                "relative rounded-full border px-4 py-1.5 text-[13px] transition-colors",
                tab === entry.id
                  ? "border-foreground/20 bg-secondary font-medium text-foreground"
                  : "text-muted-foreground hover:border-foreground/25 hover:text-foreground"
              )}
            >
              {entry.label}
              {tab === entry.id && (
                <span aria-hidden className="bg-ramp absolute inset-x-4 -bottom-[13px] h-px" />
              )}
            </button>
          ))}
        </nav>

        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.16, ease: EASE }}
            className="mt-8"
          >
            {tab === "cost" && <CostPanel />}
            {tab === "eval" && <EvalPanel />}
            {tab === "review" && <ReviewPanel onTrace={setTraceId} />}
            {tab === "ingest" && <IngestPanel />}
            {tab === "attention" && <AttentionPanel onTrace={setTraceId} />}
          </motion.div>
        </AnimatePresence>

        <p className="mt-10 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          {principal.email} · {principal.dept} · {principal.role}
        </p>
      </div>

      {traceId && <TraceViewer traceId={traceId} onClose={() => setTraceId(null)} />}
    </div>
  );
}
