"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Gauge, Plus, Square, Trash2 } from "lucide-react";

import { LogoutButton } from "@/components/logout-button";
import { PixelMark } from "@/components/pixel-mark";
import { Transcript } from "@/components/transcript";
import type { ChatMessage, Source, SqlDetail, Surface } from "@/components/transcript";
import { Button } from "@/components/ui/button";
import { readSse } from "@/lib/sse";
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
  const router = useRouter();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState<ChatMessage | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  /* A send that failed before the stream started reads as an actionable error
     just above the composer, with a retry affordance. */
  const [sendError, setSendError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  /* The in-flight turn's controller, for the Stop affordance. */
  const abortRef = useRef<AbortController | null>(null);
  /* Authoritative draft mirror: the streaming loop is the only writer, so
     handlers read the ref instead of racing a setState round-trip, and the
     finalize step does exactly one pure append. */
  const draftRef = useRef<ChatMessage | null>(null);
  /* Last query the user tried to send, for the retry affordance. */
  const lastQueryRef = useRef<string>("");
  /* View key drives the switch animation and only changes on explicit
     navigation, never when the backend assigns a new conversation id
     mid-stream. */
  const [viewKey, setViewKey] = useState<string>("new");

  /* Leaving the page cancels the stream so its tokens are not billed to a
     component nobody can see. */
  useEffect(() => () => abortRef.current?.abort(), []);

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
      id: string;
      role: "user" | "assistant";
      content: string;
      trace_id?: string | null;
      detail?: { sources?: Source[]; sql?: SqlDetail } | null;
      feedback?: { rating?: string | null; correction?: string | null } | null;
    }[];
    setMessages(
      history.map((m) => ({
        role: m.role,
        content: m.content,
        sources: m.detail?.sources,
        sql: m.detail?.sql,
        traceId: m.trace_id ?? undefined,
        uid: m.id,
        messageId: m.id,
        feedback:
          m.feedback?.rating === "up" || m.feedback?.rating === "down"
            ? m.feedback.rating
            : undefined,
        correction: m.feedback?.correction ?? undefined,
      }))
    );
  }

  function newConversation() {
    setConversationId(null);
    setViewKey("new");
    setMessages([]);
    setDraft(null);
  }

  async function deleteConversation(id: string) {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("delete failed");
      setConversations((prev) => prev.filter((item) => item.id !== id));
      if (conversationId === id) newConversation();
    } catch {
      setHistoryError("Could not delete that conversation.");
    } finally {
      setHistoryBusy(false);
      setConfirmingDelete(null);
    }
  }

  async function clearHistory() {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const res = await fetch("/api/conversations", { method: "DELETE" });
      if (!res.ok) throw new Error("clear failed");
      setConversations([]);
      newConversation();
    } catch {
      setHistoryError("Could not clear your history.");
    } finally {
      setHistoryBusy(false);
      setConfirmingClear(false);
    }
  }

  function setDraftSync(message: ChatMessage | null) {
    draftRef.current = message;
    setDraft(message);
  }

  function applyAssistant(update: (prev: ChatMessage) => ChatMessage) {
    const prev = draftRef.current;
    if (!prev) return;
    const next = update(prev);
    draftRef.current = next;
    setDraft(next);
  }

  function updateMessage(messageId: string, patch: Partial<ChatMessage>) {
    setMessages((prev) =>
      prev.map((message) =>
        message.messageId === messageId ? { ...message, ...patch } : message
      )
    );
    if (draftRef.current?.messageId === messageId) {
      const next = { ...draftRef.current, ...patch };
      draftRef.current = next;
      setDraft(next);
    }
  }

  async function submitFeedback(
    messageId: string,
    rating: "up" | "down",
    correction?: string
  ) {
    const current =
      messages.find((message) => message.messageId === messageId) ??
      (draft?.messageId === messageId ? draft : undefined);
    const previousRating = current?.feedback;
    const previousCorrection = current?.correction;
    updateMessage(messageId, {
      feedback: rating,
      correction: correction ?? previousCorrection,
    });
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message_id: messageId, rating, correction }),
      });
      if (!res.ok) throw new Error("feedback request failed");
    } catch {
      updateMessage(messageId, {
        feedback: previousRating,
        correction: previousCorrection,
      });
    }
  }

  async function send(pinned?: { query: string; surface?: Surface }) {
    const query = (pinned?.query ?? input).trim();
    if (!query || busy) return;
    if (!pinned) setInput("");
    lastQueryRef.current = query;
    setSendError(null);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const userMessage: ChatMessage = {
      role: "user",
      content: query,
      uid: `u-${seq.current++}`,
    };
    setMessages((prev) => [...prev, userMessage]);
    setDraftSync({
      role: "assistant",
      content: "",
      sources: [],
      query,
      uid: `a-${seq.current++}`,
    });

    /* A turn's conversation id arrives on every answer-path event; adopting it
       from sources *and* done (and clarify, and refusal paths) means the id is
       bound no matter which surface answered. The closure mirror also keeps
       repeated events consistent while state updates settle. */
    let turnConversationId = conversationId;
    let createdNew = false;
    let terminalSeen = false;
    const adopt = (data: Record<string, unknown>) => {
      if (!turnConversationId && data.conversation_id) {
        turnConversationId = String(data.conversation_id);
        setConversationId(turnConversationId);
        createdNew = true;
      }
    };

    const failure = (message: string) => {
      /* The turn never reached the assistant: undo the optimistic transcript
         entries and hand the query back for a retry. */
      setMessages((prev) => prev.filter((m) => m.uid !== userMessage.uid));
      setDraftSync(null);
      setInput(query);
      setSendError(message);
    };

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          query,
          conversation_id: conversationId,
          surface: pinned?.surface,
        }),
        signal: controller.signal,
      });
      if (res.status === 401) {
        // Session expired mid-chat; hand the turn back and re-login.
        failure("Your session expired. Sign in again to continue.");
        router.push("/login");
        return;
      }
      if (!res.ok || !res.body) {
        throw new Error("request failed");
      }
      await readSse(res.body, (event, data) => {
        adopt(data);
        if (event === "sources") {
          applyAssistant((m) => ({ ...m, sources: (data.sources as ChatMessage["sources"]) ?? [] }));
        } else if (event === "sql") {
          applyAssistant((m) => ({ ...m, sql: data as unknown as ChatMessage["sql"] }));
        } else if (event === "clarify") {
          applyAssistant((m) => ({ ...m, clarify: data as unknown as ChatMessage["clarify"] }));
        } else if (event === "token") {
          applyAssistant((m) => ({ ...m, content: m.content + String(data.text ?? "") }));
        } else if (event === "limit" || event === "error") {
          terminalSeen = true;
          applyAssistant((m) => ({
            ...m,
            content: String(data.message ?? "Something went wrong."),
          }));
        } else if (event === "done") {
          terminalSeen = true;
          applyAssistant((m) => ({
            ...m,
            content: String(data.answer ?? m.content),
            clarify: (data.clarify as ChatMessage["clarify"]) ?? m.clarify,
            model: String(data.model ?? ""),
            promptVersion: String(data.prompt_version ?? ""),
            traceId: String(data.trace_id ?? ""),
            messageId:
              typeof data.message_id === "string" && data.message_id
                ? data.message_id
                : m.messageId,
          }));
        }
      });
      if (createdNew) refreshConversations();
    } catch (streamError) {
      const userStopped =
        streamError instanceof Error && streamError.name === "AbortError";
      if (userStopped) {
        applyAssistant((m) => ({ ...m, stopReason: "user" }));
      } else if (!terminalSeen) {
        failure("Could not reach the assistant. Your message was not sent.");
      } else {
        applyAssistant((m) => ({ ...m, content: m.content || "Something went wrong." }));
      }
    } finally {
      /* Exactly one pure append per turn: the draft snapshot comes from the
         ref, never from inside a setState updater. */
      const finalDraft = draftRef.current;
      if (finalDraft) {
        const cutShort = !terminalSeen && !finalDraft.stopReason;
        const finalMessage: ChatMessage = {
          ...finalDraft,
          content: finalDraft.content || (cutShort ? "" : ""),
          stopReason: finalDraft.stopReason ?? (cutShort ? "connection" : undefined),
        };
        setMessages((existing) => [...existing, finalMessage]);
        setDraftSync(null);
      }
      setBusy(false);
      abortRef.current = null;
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
            <div className="flex items-center justify-between px-4 pb-1 pt-2">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                Recent
              </p>
              {conversations.length > 0 && !confirmingClear && (
                <button
                  type="button"
                  disabled={historyBusy}
                  onClick={() => {
                    setHistoryError(null);
                    setConfirmingClear(true);
                  }}
                  className="text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                >
                  Clear all
                </button>
              )}
            </div>
            {confirmingClear && (
              <div className="mx-3 mb-2 rounded-md border bg-secondary/50 px-3 py-2">
                <p className="text-xs text-muted-foreground">
                  Delete every conversation and its history?
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    disabled={historyBusy}
                    onClick={() => void clearHistory()}
                    className="rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/85 disabled:opacity-50"
                  >
                    Delete all
                  </button>
                  <button
                    type="button"
                    disabled={historyBusy}
                    onClick={() => setConfirmingClear(false)}
                    className="rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
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
                    {confirmingDelete === conversation.id ? (
                      <div className="px-4 py-2">
                        <p className="truncate text-sm text-muted-foreground">
                          Delete this conversation?
                        </p>
                        <div className="mt-1.5 flex items-center gap-2">
                          <button
                            type="button"
                            disabled={historyBusy}
                            onClick={() => void deleteConversation(conversation.id)}
                            className="rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/85 disabled:opacity-50"
                          >
                            Delete
                          </button>
                          <button
                            type="button"
                            disabled={historyBusy}
                            onClick={() => setConfirmingDelete(null)}
                            className="rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="group relative flex items-center">
                        <button
                          onClick={() => openConversation(conversation.id)}
                          className={cn(
                            "relative block w-full truncate py-2 pl-4 pr-9 text-left text-sm transition-colors",
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
                        <button
                          type="button"
                          title="Delete conversation"
                          aria-label={`Delete ${conversation.title ?? "conversation"}`}
                          disabled={historyBusy}
                          onClick={() => {
                            setHistoryError(null);
                            setConfirmingDelete(conversation.id);
                          }}
                          className="absolute right-2 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-0"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </motion.li>
                ))}
              </ul>
            )}
            {historyError && (
              <p className="px-4 py-1 text-xs text-brand-vermilion">{historyError}</p>
            )}
          </nav>
          <div className="border-t p-3">
            {principal.role === "admin" && (
              <Link
                href="/admin"
                className="mb-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <Gauge className="h-4 w-4" />
                Admin console
              </Link>
            )}
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
                          onFeedback={(messageId, rating, correction) =>
                            void submitFeedback(messageId, rating, correction)
                          }
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              </AnimatePresence>
            </div>
          </div>

          {sendError && (
            <div className="mx-auto flex w-full max-w-4xl items-center justify-between gap-3 px-4 md:px-6">
              <p className="text-sm text-destructive">{sendError}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void send(lastQueryRef.current ? { query: lastQueryRef.current } : undefined)}
              >
                Retry
              </Button>
            </div>
          )}

          <form
            className="mx-auto flex w-full max-w-4xl items-center gap-2 px-4 py-4 md:px-6"
            onSubmit={(event) => {
              event.preventDefault();
              if (busy) return;
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
              {busy ? (
                <motion.button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  aria-label="Stop generating"
                  whileTap={{ scale: 0.88 }}
                  transition={spring}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground transition-colors hover:bg-secondary/80"
                >
                  <Square className="h-4 w-4 fill-current" />
                </motion.button>
              ) : (
                <motion.button
                  type="submit"
                  disabled={!input.trim()}
                  aria-label="Send"
                  whileTap={{ scale: 0.88 }}
                  transition={spring}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/85 disabled:bg-secondary disabled:text-muted-foreground"
                >
                  <ArrowUp className="h-4 w-4" />
                </motion.button>
              )}
              <motion.span
                aria-hidden
                className="bg-ramp absolute inset-x-0 bottom-0 h-[2px] origin-left"
                initial={false}
                animate={{ scaleX: busy || composerFocused ? 1 : 0 }}
                transition={{ duration: 0.25, ease: EASE }}
              />
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}
