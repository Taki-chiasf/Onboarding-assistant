"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";

import { Empty, ErrorNote, Flag, Loading } from "@/components/admin/ui";
import { cn } from "@/lib/utils";
import { EASE } from "@/lib/motion";

type Span = {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string | null;
  start_ms: number;
  duration_ms: number;
  status: string;
  attributes: Record<string, string>;
};

type TraceView = { trace_id: string; found: boolean; spans: Span[] };

function depthOf(span: Span, byId: Map<string, Span>): number {
  let depth = 0;
  let parent = span.parent_span_id;
  const seen = new Set<string>([span.span_id]);
  while (parent && byId.has(parent) && !seen.has(parent)) {
    seen.add(parent);
    depth += 1;
    parent = byId.get(parent)?.parent_span_id ?? null;
    if (depth > 20) break;
  }
  return depth;
}

function duration(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  if (value >= 10) return `${value.toFixed(0)}ms`;
  return `${value.toFixed(1)}ms`;
}

export function TraceViewer({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [data, setData] = useState<TraceView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    fetch(`/api/admin/traces/${encodeURIComponent(traceId)}`, { cache: "no-store" })
      .then(async (res) => {
        const body = (await res.json().catch(() => null)) as
          | (TraceView & { detail?: string })
          | null;
        if (!res.ok) throw new Error(body?.detail ?? `trace request failed: ${res.status}`);
        return body as TraceView;
      })
      .then((body) => active && setData(body))
      .catch((cause: unknown) =>
        active
          ? setError(cause instanceof Error ? cause.message : "Could not load the trace.")
          : undefined
      );
    return () => {
      active = false;
    };
  }, [traceId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const total = data?.spans.length
    ? Math.max(...data.spans.map((span) => span.start_ms + span.duration_ms), 0.1)
    : 1;
  const byId = new Map((data?.spans ?? []).map((span) => [span.span_id, span]));

  return (
    <AnimatePresence>
      <motion.div
        key="backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <motion.aside
        key="drawer"
        initial={{ x: 24, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 24, opacity: 0 }}
        transition={{ duration: 0.2, ease: EASE }}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l bg-background shadow-lift"
        role="dialog"
        aria-label="Trace viewer"
      >
        <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
          <div className="min-w-0">
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              Trace
            </p>
            <p className="truncate font-mono text-[11px]">{traceId}</p>
          </div>
          <button
            type="button"
            aria-label="Close trace viewer"
            onClick={onClose}
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {error ? (
            <ErrorNote>{error}</ErrorNote>
          ) : !data ? (
            <Loading label="Fetching spans" />
          ) : !data.found || data.spans.length === 0 ? (
            <Empty>
              No spans found. The trace may have aged out of the backend&apos;s retention window.
            </Empty>
          ) : (
            <ul className="space-y-1">
              {data.spans.map((span) => {
                const depth = depthOf(span, byId);
                const left = (span.start_ms / total) * 100;
                const width = Math.max((span.duration_ms / total) * 100, 0.6);
                return (
                  <li key={span.span_id} className="border-b pb-2 last:border-b-0">
                    <div
                      className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1"
                      style={{ paddingLeft: 8 + depth * 14 }}
                    >
                      <span className="flex min-w-0 items-baseline gap-2">
                        <span
                          aria-hidden
                          className={cn(
                            "h-1.5 w-1.5 shrink-0 self-center rounded-full",
                            span.status === "error" ? "bg-destructive" : "bg-brand-orange"
                          )}
                        />
                        <span className="truncate text-sm">{span.name}</span>
                        {span.kind && (
                          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                            {span.kind}
                          </span>
                        )}
                      </span>
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        {duration(span.duration_ms)}
                      </span>
                    </div>
                    <div
                      className="mt-1.5 h-[6px] rounded-full bg-secondary"
                      style={{ marginLeft: 8 + depth * 14 }}
                    >
                      <div
                        className={cn(
                          "h-full rounded-full",
                          span.status === "error" ? "bg-destructive" : "bg-ramp"
                        )}
                        style={{ marginLeft: `${left * 0.9}%`, width: `${width * 0.9}%` }}
                      />
                    </div>
                    {Object.keys(span.attributes).length > 0 && (
                      <p
                        className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted-foreground"
                        style={{ paddingLeft: 8 + depth * 14 }}
                      >
                        {Object.entries(span.attributes).map(([key, value]) => (
                          <span key={key} className="truncate">
                            {key}=<span className="text-foreground/70">{value}</span>
                          </span>
                        ))}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <footer className="shrink-0 border-t px-4 py-3">
          {data?.found && (
            <p className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <Flag>{data.spans.length} spans</Flag>
              <span>total {duration(total)}</span>
            </p>
          )}
        </footer>
      </motion.aside>
    </AnimatePresence>
  );
}
