"use client";

import { useEffect, useState } from "react";

import { Empty, ErrorNote, Flag, Loading } from "@/components/admin/ui";
import { Button } from "@/components/ui/button";

type AttentionItem = {
  message_id: string;
  question: string | null;
  answer: string;
  reasons: string[];
  intent: string | null;
  confidence: number | null;
  trace_id: string | null;
  user_id: string | null;
  created_at: string;
};

const REASON_LABELS: Record<string, string> = {
  dont_know: "no answer",
  low_confidence: "low confidence",
};

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AttentionPanel({ onTrace }: { onTrace: (traceId: string) => void }) {
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/admin/attention?limit=30", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: { items: AttentionItem[] }) => active && setItems(body.items))
      .catch(() => active && setError("Could not load the attention list."));
    return () => {
      active = false;
    };
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <Loading />;

  if (items.length === 0) {
    return (
      <Empty>
        Nothing needs attention. Questions the assistant could not answer or routed
        uncertainly show up here.
      </Empty>
    );
  }

  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.message_id} className="border">
          <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="text-[15px] font-medium">
                {item.question ?? "Question not found for this turn."}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {item.reasons.map((reason) => (
                  <Flag key={reason} tone={reason === "dont_know" ? "error" : "warn"}>
                    {REASON_LABELS[reason] ?? reason}
                  </Flag>
                ))}
                {item.intent && <Flag>{item.intent}</Flag>}
                {typeof item.confidence === "number" && (
                  <Flag tone={item.confidence < 0.5 ? "warn" : "neutral"}>
                    conf {item.confidence.toFixed(2)}
                  </Flag>
                )}
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                  {item.user_id ?? "unknown"} · {when(item.created_at)}
                </span>
              </div>
            </div>
            {item.trace_id && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => onTrace(item.trace_id!)}
              >
                Trace
              </Button>
            )}
          </div>
          <p className="truncate border-t bg-secondary/40 px-4 py-2 text-sm text-muted-foreground">
            {item.answer}
          </p>
        </li>
      ))}
    </ul>
  );
}
