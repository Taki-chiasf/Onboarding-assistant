"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Plus } from "lucide-react";

import { LogoutButton } from "@/components/logout-button";
import { PixelMark } from "@/components/pixel-mark";
import { Transcript } from "@/components/transcript";
import type { ChatMessage, Source, SqlDetail, Surface } from "@/components/transcript";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { EASE, riseIn, stagger, spring, transition } from "@/lib/motion";

type ConversationSummary = {
  id: string;
  title: string | null;
  created_at: string;
};

type Principal = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

const SUGGESTIONS = [
  "How many days of parental leave do I get?",
  "What is the expense limit for a team dinner?",
  "How do I get my laptop set up?",
];

async function readSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice("event: ".length).trim();
        else if (line.startsWith("data: ")) data += line.slice("data: ".length);
      }
      if (!data) continue;
      try {
        onEvent(event, JSON.parse(data) as Record<string, unknown>);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

function EmptyState({
  busy,
  onSuggest,
}: {
  busy: boolean;
  onSuggest: (query: string) => void;
}) {
  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="visible"
      className="relative flex flex-col items-center pt-[18vh] text-center"
    >
      <div
        aria-hidden
        className="ambient-wash pointer-events-none absolute inset-x-0 -top-10 h-96"
      />
      <motion.div variants={riseIn}>
        <PixelMark className="h-9 w-9" />
      </motion.div>
      <motion.h2
        variants={riseIn}
        className="mt-6 text-[32px] font-semibold tracking-tight"
      >
        How can I help you settle in
        <span className="text-brand-vermilion">?</span>
      </motion.h2>
      <motion.p
        variants={riseIn}
        className="mt-3 max-w-sm text-[15px] leading-relaxed text-muted-foreground"
      >
        Ask about company policy, teams, or tooling. Every answer cites its
        sources.
      </motion.p>
      <motion.div variants={riseIn} className="mt-8 flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <motion.button
            key={suggestion}
            type="button"
            disabled={busy}
            onClick={() => onSuggest(suggestion)}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.97 }}
            transition={spring}
            className="rounded-full border px-4 py-2 text-[13px] text-muted-foreground transition-colors hover:border-foreground/25 hover:bg-secondary hover:text-foreground hover:shadow-lift disabled:pointer-events-none disabled:opacity-50"
          >
            {suggestion}
          </motion.button>
        ))}
      </motion.div>
    </motion.div>
  );
}

export function Chat({ principal }: { principal: Principal }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState<ChatMessage | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  /* View key drives the switch animation and only changes on explicit
     navigation, never when the backend assigns a new conversation id
     mid-stream. */
  const [viewKey, setViewKey] = useState<string>("new");

  useEffect(() => {
    fetch("/api/conversations")
      .then((res) => (res.ok ? res.json() : []))
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, draft]);

  function refreshConversations() {
    fetch("/api/conversations")
      .then((res) => (res.ok ? res.json() : []))
      .then(setConversations)
      .catch(() => undefined);
  }

  async function openConversation(id: string) {
    setConversationId(id);
    setViewKey(id);
    setDraft(null);
    const res = await fetch(`/api/conversations/${id}/messages`);
    if (!res.ok) return;
    const history = (await res.json()) as {
      role: "user" | "assistant";
      content: string;
      trace_id?: string | null;
      detail?: { sources?: Source[]; sql?: SqlDetail } | null;
    }[];
    setMessages(
      history.map((m) => ({
        role: m.role,
        content: m.content,
        sources: m.detail?.sources,
        sql: m.detail?.sql,
        traceId: m.trace_id ?? undefined,
      }))
    );
  }

  function newConversation() {
    setConversationId(null);
    setViewKey("new");
    setMessages([]);
    setDraft(null);
  }

  function applyAssistant(update: (prev: ChatMessage) => ChatMessage) {
    setDraft((prev) => (prev ? update(prev) : prev));
  }

  async function send(pinned?: { query: string; surface?: Surface }) {
    const query = (pinned?.query ?? input).trim();
    if (!query || busy) return;
    if (!pinned) setInput("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: query, uid: `u-${seq.current++}` },
    ]);
    setDraft({ role: "assistant", content: "", sources: [], query, uid: `a-${seq.current++}` });

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          query,
          conversation_id: conversationId,
          surface: pinned?.surface,
        }),
      });
      if (!res.ok || !res.body) {
        throw new Error("request failed");
      }
      let createdNew = false;
      await readSse(res.body, (event, data) => {
        if (event === "sources") {
          if (!conversationId && data.conversation_id) {
            setConversationId(String(data.conversation_id));
            createdNew = true;
          }
          applyAssistant((m) => ({ ...m, sources: (data.sources as ChatMessage["sources"]) ?? [] }));
        } else if (event === "sql") {
          applyAssistant((m) => ({ ...m, sql: data as unknown as ChatMessage["sql"] }));
        } else if (event === "clarify") {
          applyAssistant((m) => ({ ...m, clarify: data as unknown as ChatMessage["clarify"] }));
        } else if (event === "token") {
          applyAssistant((m) => ({ ...m, content: m.content + String(data.text ?? "") }));
        } else if (event === "done") {
          applyAssistant((m) => ({
            ...m,
            content: String(data.answer ?? m.content),
            clarify: (data.clarify as ChatMessage["clarify"]) ?? m.clarify,
            model: String(data.model ?? ""),
            promptVersion: String(data.prompt_version ?? ""),
            traceId: String(data.trace_id ?? ""),
          }));
        }
      });
      if (createdNew) refreshConversations();
    } catch {
      applyAssistant((m) => ({ ...m, content: m.content || "Something went wrong." }));
    } finally {
      setDraft((prev) => {
        if (prev) setMessages((existing) => [...existing, prev]);
        return null;
      });
      setBusy(false);
    }
  }

  const visible = draft ? [...messages, draft] : messages;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b px-4 md:hidden">
        <div className="flex min-w-0 items-center gap-2.5">
          <PixelMark className="h-[15px] w-[15px]" assemble={false} />
          <span className="truncate text-sm font-semibold tracking-tight">
            Onboarding Assistant
          </span>
        </div>
        <LogoutButton compact />
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 flex-col border-r md:flex">
          <div className="flex h-12 shrink-0 items-center gap-2.5 border-b px-4">
            <PixelMark className="h-[18px] w-[18px]" assemble={false} />
            <span className="text-sm font-semibold tracking-tight">Onboarding Assistant</span>
          </div>
          <div className="p-3">
            <Button className="w-full" onClick={newConversation}>
              <Plus className="h-4 w-4" />
              New conversation
            </Button>
          </div>
          <nav className="flex-1 overflow-y-auto pb-3">
            <p className="px-4 pb-1 pt-2 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              Recent
            </p>
            {conversations.length === 0 ? (
              <p className="px-4 py-2 text-xs text-muted-foreground">No conversations yet.</p>
            ) : (
              <ul>
                {conversations.map((conversation) => (
                  <motion.li
                    key={conversation.id}
                    layout
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={transition}
                  >
                    <button
                      onClick={() => openConversation(conversation.id)}
                      className={cn(
                        "relative block w-full truncate px-4 py-2 text-left text-sm transition-colors",
                        conversation.id === conversationId
                          ? "bg-secondary font-medium text-foreground"
                          : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                      )}
                    >
                      {conversation.id === conversationId && (
                        <span
                          aria-hidden
                          className="bg-ramp-v absolute inset-y-[6px] left-0 w-px"
                        />
                      )}
                      {conversation.title ?? "Untitled"}
                    </button>
                  </motion.li>
                ))}
              </ul>
            )}
          </nav>
          <div className="border-t p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-xs font-medium">{principal.email}</p>
                <p className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                  {principal.dept} · {principal.role}
                </p>
              </div>
              <LogoutButton />
            </div>
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-6">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={viewKey}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.18, ease: EASE }}
                >
                  <AnimatePresence mode="wait" initial={false}>
                    {visible.length === 0 ? (
                      <motion.div
                        key="empty"
                        exit={{ opacity: 0, y: -10, transition: { duration: 0.18, ease: EASE } }}
                      >
                        <EmptyState busy={busy} onSuggest={(q) => void send({ query: q })} />
                      </motion.div>
                    ) : (
                      <motion.div key="transcript" initial={false}>
                        <Transcript
                          messages={visible}
                          busy={busy}
                          onClarify={(query, surface) => void send({ query, surface })}
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              </AnimatePresence>
            </div>
          </div>

          <form
            className="mx-auto flex w-full max-w-4xl items-center gap-2 px-4 py-4 md:px-6"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <div
              className={cn(
                "relative flex min-w-0 flex-1 items-center gap-2 overflow-hidden rounded-xl border bg-background py-1.5 pl-4 pr-1.5 transition-all duration-200",
                "focus-within:border-foreground/40 focus-within:shadow-lift"
              )}
            >
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onFocus={() => setComposerFocused(true)}
                onBlur={() => setComposerFocused(false)}
                placeholder="Ask about parental leave, expenses, laptop setup…"
                className="min-w-0 flex-1 bg-transparent py-1.5 text-[16px] outline-none caret-brand-orange placeholder:text-muted-foreground"
              />
              <motion.button
                type="submit"
                disabled={busy || !input.trim()}
                aria-label="Send"
                whileTap={{ scale: 0.88 }}
                transition={spring}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/85 disabled:bg-secondary disabled:text-muted-foreground"
              >
                <ArrowUp className="h-4 w-4" />
              </motion.button>
              <motion.span
                aria-hidden
                className="bg-ramp absolute inset-x-0 bottom-0 h-[2px] origin-left"
                initial={false}
                animate={{ scaleX: composerFocused ? 1 : 0 }}
                transition={{ duration: 0.25, ease: EASE }}
              />
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}
