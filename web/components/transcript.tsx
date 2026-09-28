"use client";

import { useEffect, useId, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThumbsDown, ThumbsUp } from "lucide-react";

import { PixelCursor } from "@/components/pixel-mark";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { EASE, riseIn, stagger, transition } from "@/lib/motion";

export type Source = {
  id: string;
  source_uri: string;
  section_anchor: string;
  score: number;
};

export type SqlDetail = {
  sql: string;
  row_count: number;
  truncated: boolean;
  latency_ms: number;
};

export type Surface = "rag-docs" | "rag-code" | "text-to-sql";

export type ClarifyOption = {
  surface: Surface;
  label: string;
};

export type Clarify = {
  kind: "surface" | "interpretation";
  question: string;
  options: ClarifyOption[];
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  sql?: SqlDetail;
  clarify?: Clarify;
  query?: string;
  model?: string;
  promptVersion?: string;
  traceId?: string;
  /* Server-side message id, the target for feedback. */
  messageId?: string;
  /* The caller's saved rating, rehydrated on reload. */
  feedback?: "up" | "down";
  correction?: string;
  /* Client-side identity, stable from streaming draft through the
     finalized turn, so a completed answer never re-runs its entrance. */
  uid?: string;
};

function stripCitations(content: string): string {
  return content.replace(/\[\d+\](?!\()/g, "");
}

const TAB_LABELS = {
  sources: "Sources",
  sql: "SQL",
  trace: "Raw trace",
} as const;

/* Ramp positions for the docket dots that mark each cited source. */
const DOCKET_DOTS = ["#ffaf01", "#ff8204", "#fa500f", "#e61300", "#c4001d"];

function docketDot(i: number): string {
  return DOCKET_DOTS[i % DOCKET_DOTS.length];
}

export function SourcePanel({
  sources,
  sql,
  traceId,
}: {
  sources: Source[];
  sql?: SqlDetail;
  traceId?: string;
}) {
  const [tab, setTab] = useState<"sources" | "sql" | "trace">("sources");
  const panelId = useId();

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 400, damping: 32 }}
      className="mt-3 rounded-lg border text-xs shadow-lift"
    >
      <div className="flex gap-5 border-b px-3">
        {(["sources", "sql", "trace"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "relative py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors",
              tab === key ? "text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {TAB_LABELS[key]}
            {tab === key && (
              <motion.span
                layoutId={`evidence-tab-${panelId}`}
                className="bg-ramp absolute inset-x-0 -bottom-px h-[2px] rounded-full"
                transition={{ type: "spring", stiffness: 500, damping: 35 }}
              />
            )}
          </button>
        ))}
      </div>
      <div className="overflow-hidden p-3">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15, ease: EASE }}
          >
            {tab === "sources" &&
              (sources.length > 0 ? (
                <ul className="divide-y">
                  {sources.map((source, i) => (
                    <motion.li
                      key={source.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.25,
                        ease: EASE,
                        delay: Math.min(i * 0.05, 0.3),
                      }}
                      className="py-2 first:pt-0 last:pb-0"
                    >
                      <div className="flex items-start gap-2.5">
                        <span
                          aria-hidden
                          className="mt-[5px] h-[6px] w-[6px] shrink-0"
                          style={{ background: docketDot(i) }}
                        />
                        <div className="min-w-0">
                          <p className="truncate font-medium">{source.section_anchor}</p>
                          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                            {source.source_uri}
                          </p>
                        </div>
                      </div>
                    </motion.li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">No sources recorded for this answer.</p>
              ))}
            {tab === "sql" &&
              (sql ? (
                <div>
                  <p className="text-muted-foreground">
                    {sql.row_count} row{sql.row_count === 1 ? "" : "s"} in {sql.latency_ms}ms
                    {sql.truncated ? " (truncated)" : ""}
                  </p>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2.5 font-mono text-[11px] leading-relaxed text-muted-foreground">
                    {sql.sql}
                  </pre>
                </div>
              ) : (
                <p className="text-muted-foreground">No live data query for this answer.</p>
              ))}
            {tab === "trace" && (
              <p className="break-all font-mono text-[11px] text-muted-foreground">
                {traceId ?? "Trace not recorded."}
              </p>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

export function AnswerFeedback({
  messageId,
  rating,
  correction,
  onFeedback,
}: {
  messageId: string;
  rating?: "up" | "down";
  correction?: string;
  onFeedback: (messageId: string, rating: "up" | "down", correction?: string) => void;
}) {
  const [draft, setDraft] = useState(correction ?? "");
  const [sent, setSent] = useState(false);
  const down = rating === "down";

  useEffect(() => {
    setDraft(correction ?? "");
  }, [correction]);

  return (
    <div className="mt-2 flex items-center gap-1">
      <button
        type="button"
        aria-label="Helpful"
        aria-pressed={rating === "up"}
        onClick={() => onFeedback(messageId, "up")}
        className={cn(
          "rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
          rating === "up" && "bg-secondary text-foreground"
        )}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        aria-label="Not helpful"
        aria-pressed={down}
        onClick={() => onFeedback(messageId, "down")}
        className={cn(
          "rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
          down && "bg-secondary text-foreground"
        )}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
      <AnimatePresence initial={false}>
        {down && (
          <motion.form
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -4 }}
            transition={{ duration: 0.15, ease: EASE }}
            className="flex min-w-0 max-w-md flex-1 items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              const text = draft.trim();
              if (!text) return;
              onFeedback(messageId, "down", text);
              setSent(true);
            }}
          >
            <input
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setSent(false);
              }}
              placeholder="What was missing or wrong?"
              className="min-w-0 flex-1 rounded-md border bg-background px-2.5 py-1.5 text-xs outline-none transition-colors focus:border-foreground/40"
            />
            <button
              type="submit"
              disabled={!draft.trim()}
              className="shrink-0 rounded-md border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-foreground/25 hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
            >
              Send
            </button>
            {sent && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="shrink-0 text-xs text-muted-foreground"
              >
                Noted for review
              </motion.span>
            )}
          </motion.form>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Transcript({
  messages,
  busy,
  onClarify,
  onFeedback,
}: {
  messages: ChatMessage[];
  busy: boolean;
  onClarify: (query: string, surface: Surface) => void;
  onFeedback: (messageId: string, rating: "up" | "down", correction?: string) => void;
}) {
  return (
    <div className="space-y-6">
      {messages.map((message) =>
        message.role === "user" ? (
          <motion.div
            key={message.uid ?? `u-${message.content}`}
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className="flex justify-end"
          >
            <div className="max-w-[85%] rounded-2xl bg-secondary px-4 py-2.5 text-[16px] leading-relaxed">
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key={message.uid ?? `a-${message.content}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transition}
            className="text-[16px] leading-relaxed"
          >
            {message.content ? (
              <div className="prose prose-neutral max-w-none whitespace-pre-wrap prose-headings:font-semibold prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0 prose-pre:overflow-x-auto prose-pre:rounded-md prose-pre:bg-muted prose-pre:p-3 prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-a:text-brand-vermilion prose-a:underline prose-a:underline-offset-2">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {stripCitations(message.content)}
                </ReactMarkdown>
              </div>
            ) : (
              <PixelCursor />
            )}
            {message.clarify && message.query && (
              <motion.div
                initial="hidden"
                animate="visible"
                variants={stagger}
                className="mt-3 flex flex-wrap gap-2"
              >
                {message.clarify.options.map((option) => (
                  <motion.div key={option.surface} variants={riseIn}>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => onClarify(message.query ?? "", option.surface)}
                    >
                      {option.label}
                    </Button>
                  </motion.div>
                ))}
              </motion.div>
            )}
            {((message.sources && message.sources.length > 0) || message.sql) && (
              <SourcePanel
                sources={message.sources ?? []}
                sql={message.sql}
                traceId={message.traceId}
              />
            )}
            {message.messageId && (
              <AnswerFeedback
                messageId={message.messageId}
                rating={message.feedback}
                correction={message.correction}
                onFeedback={onFeedback}
              />
            )}
          </motion.div>
        )
      )}
    </div>
  );
}
