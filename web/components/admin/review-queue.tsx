"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";

import { Empty, ErrorNote, Flag, Loading } from "@/components/admin/ui";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { transition } from "@/lib/motion";

type ReviewCase = {
  id: string;
  prompt: string;
  status: string;
  source: string | null;
  tags: string[] | null;
  created_at: string;
  expected_intent: string | null;
  expected_source_ids: string[] | null;
  expected_sql_pattern: string | null;
  expected_rows_predicate: string | null;
  message_id: string | null;
  trace_id: string | null;
  rating: string | null;
  correction: string | null;
  detail: {
    route?: { intent?: string; router_confidence?: number };
    sources?: unknown[];
    sql?: { sql?: string };
  } | null;
};

const INTENTS = ["", "rag-docs", "rag-code", "text-to-sql", "out-of-scope", "ambiguous"];

const SOURCE_LABELS: Record<string, string> = {
  thumbs_down: "thumbs down",
  correction: "correction",
  misroute: "router misroute",
};

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ReviewPanel({ onTrace }: { onTrace: (traceId: string) => void }) {
  const [cases, setCases] = useState<ReviewCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [intent, setIntent] = useState("");
  const [sourceIds, setSourceIds] = useState("");
  const [sqlPattern, setSqlPattern] = useState("");
  const [rowsPredicate, setRowsPredicate] = useState("");

  async function load() {
    try {
      const res = await fetch("/api/admin/review", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as { cases: ReviewCase[] };
      setCases(body.cases);
      setError(null);
    } catch {
      setError("Could not load the review queue.");
      setCases(null);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function startReview(item: ReviewCase) {
    setReviewing(item.id);
    setNotice(null);
    setIntent(item.expected_intent ?? "");
    setSourceIds((item.expected_source_ids ?? []).join(", "));
    setSqlPattern(item.expected_sql_pattern ?? "");
    setRowsPredicate(item.expected_rows_predicate ?? "");
  }

  async function decide(item: ReviewCase, action: "promote" | "reject") {
    setBusy(item.id);
    setNotice(null);
    try {
      const payload =
        action === "promote"
          ? {
              expected_intent: intent || null,
              expected_source_ids: sourceIds
                .split(",")
                .map((value) => value.trim())
                .filter(Boolean),
              expected_sql_pattern: sqlPattern.trim() || null,
              expected_rows_predicate: rowsPredicate.trim() || null,
            }
          : {};
      const res = await fetch(`/api/admin/review/${item.id}/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(detail?.detail ?? `request failed: ${res.status}`);
      }
      setCases((prev) => (prev ?? []).filter((entry) => entry.id !== item.id));
      setReviewing(null);
      setNotice(
        action === "promote"
          ? `Promoted “${item.prompt}” into the eval set.`
          : `Rejected “${item.prompt}”.`
      );
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : "Review action failed.");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (cases === null) return <Loading />;

  const canPromote = Boolean(
    intent || sourceIds.trim() || sqlPattern.trim() || rowsPredicate.trim()
  );

  return (
    <div className="space-y-4">
      {notice && (
        <p className="border bg-secondary/60 px-4 py-2.5 text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      {cases.length === 0 ? (
        <Empty>
          Nothing waiting for review. Thumbs-down answers and router misroutes file here.
        </Empty>
      ) : (
        cases.map((item) => (
          <motion.article
            key={item.id}
            layout
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transition}
            className="border"
          >
            <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="text-[15px] font-medium">{item.prompt}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Flag tone="warn">{SOURCE_LABELS[item.source ?? ""] ?? item.source}</Flag>
                  {item.rating && <Flag>rating {item.rating}</Flag>}
                  {item.tags?.map((tag) => <Flag key={tag}>{tag}</Flag>)}
                  <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {when(item.created_at)}
                  </span>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {item.trace_id && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onTrace(item.trace_id!)}
                  >
                    Trace
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy === item.id}
                  onClick={() => (reviewing === item.id ? setReviewing(null) : startReview(item))}
                >
                  {reviewing === item.id ? "Close" : "Review"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy === item.id}
                  onClick={() => void decide(item, "reject")}
                >
                  Reject
                </Button>
              </div>
            </div>

            {item.correction && (
              <p className="border-t bg-secondary/40 px-4 py-2.5 text-sm text-muted-foreground">
                “{item.correction}”
              </p>
            )}

            {item.detail && (
              <div className="border-t px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
                {item.detail.route?.intent && (
                  <span>
                    routed {item.detail.route.intent}
                    {typeof item.detail.route.router_confidence === "number" &&
                      ` (${item.detail.route.router_confidence.toFixed(2)})`}
                  </span>
                )}
                {item.detail.sources && item.detail.sources.length > 0 && (
                  <span> · {item.detail.sources.length} sources</span>
                )}
                {item.detail.sql?.sql && (
                  <span className="block truncate"> · {item.detail.sql.sql}</span>
                )}
              </div>
            )}

            {reviewing === item.id && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={transition}
                className="border-t bg-secondary/20 px-4 py-4"
              >
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  Expectations · at least one is required to promote
                </p>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="block text-xs text-muted-foreground">
                    Expected intent
                    <select
                      value={intent}
                      onChange={(event) => setIntent(event.target.value)}
                      className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-foreground/40"
                    >
                      {INTENTS.map((value) => (
                        <option key={value || "none"} value={value}>
                          {value || "—"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-muted-foreground">
                    Expected source ids (comma separated)
                    <input
                      value={sourceIds}
                      onChange={(event) => setSourceIds(event.target.value)}
                      placeholder="file:policies/parental-leave.md"
                      className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-foreground/40"
                    />
                  </label>
                  <label className="block text-xs text-muted-foreground">
                    Expected SQL pattern (regex)
                    <input
                      value={sqlPattern}
                      onChange={(event) => setSqlPattern(event.target.value)}
                      placeholder="count\(\*\).*org_members"
                      className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-foreground/40"
                    />
                  </label>
                  <label className="block text-xs text-muted-foreground">
                    Rows predicate
                    <input
                      value={rowsPredicate}
                      onChange={(event) => setRowsPredicate(event.target.value)}
                      placeholder="count >= 1"
                      className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-foreground/40"
                    />
                  </label>
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={!canPromote || busy === item.id}
                    className={cn(!canPromote && "opacity-60")}
                    onClick={() => void decide(item, "promote")}
                  >
                    Promote to eval set
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Promoted cases replay in the nightly run.
                  </span>
                </div>
              </motion.div>
            )}
          </motion.article>
        ))
      )}
    </div>
  );
}
