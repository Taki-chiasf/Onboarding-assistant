"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  sql?: SqlDetail;
  model?: string;
  promptVersion?: string;
  traceId?: string;
};

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
};async function readSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void,
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

function SourcePanel({
  sources,
  sql,
  traceId,
}: {
  sources: Source[];
  sql?: SqlDetail;
  traceId?: string;
}) {
  const [tab, setTab] = useState<"sources" | "sql" | "trace">("sources");

  return (
    <div className="mt-2 rounded-md border text-xs">
      <div className="flex gap-1 border-b px-2 pt-1">
        {(["sources", "sql", "trace"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "rounded-t px-2 py-1 capitalize",
              tab === key ? "bg-muted font-medium" : "text-muted-foreground",
            )}
          >
            {key === "trace" ? "Raw trace" : key}
          </button>
        ))}
      </div>
      <div className="p-2">
        {tab === "sources" && (
          <ul className="space-y-1.5">
            {sources.map((source) => (
              <li key={source.id} className="rounded border p-1.5">
                <div className="font-medium text-foreground">{source.section_anchor}</div>
                <div className="truncate text-muted-foreground">{source.source_uri}</div>
              </li>
            ))}
          </ul>
        )}
        {tab === "sql" &&
          (sql ? (
            <details>
              <summary className="cursor-pointer font-medium text-foreground">
                {sql.row_count} row{sql.row_count === 1 ? "" : "s"} in {sql.latency_ms}ms
                {sql.truncated ? " (truncated)" : ""}
              </summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded bg-muted p-2 text-muted-foreground">
                {sql.sql}
              </pre>
            </details>
          ) : (
            <p className="text-muted-foreground">No live data query for this answer.</p>
          ))}
        {tab === "trace" && (
          <p className="break-all text-muted-foreground">{traceId ?? "Trace not recorded."}</p>
        )}
      </div>
    </div>
  );
}

export function Chat({ principal }: { principal: Principal }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState<ChatMessage | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

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
    setDraft(null);
    const res = await fetch(`/api/conversations/${id}/messages`);
    if (!res.ok) return;
    const history = (await res.json()) as { role: "user" | "assistant"; content: string }[];
    setMessages(history.map((m) => ({ role: m.role, content: m.content })));
  }

  function newConversation() {
    setConversationId(null);
    setMessages([]);
    setDraft(null);
  }

  function applyAssistant(update: (prev: ChatMessage) => ChatMessage) {
    setDraft((prev) => (prev ? update(prev) : prev));
  }

  async function send() {
    const query = input.trim();
    if (!query || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setDraft({ role: "assistant", content: "", sources: [] });

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query, conversation_id: conversationId }),
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
          applyAssistant((m) => ({ ...m, sources: (data.sources as Source[]) ?? [] }));
        } else if (event === "sql") {
          applyAssistant((m) => ({ ...m, sql: data as unknown as SqlDetail }));
        } else if (event === "token") {
          applyAssistant((m) => ({ ...m, content: m.content + String(data.text ?? "") }));
        } else if (event === "done") {
          applyAssistant((m) => ({
            ...m,
            content: String(data.answer ?? m.content),
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
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r md:flex">
        <div className="border-b p-3">
          <Button className="w-full" onClick={newConversation}>
            New conversation
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => openConversation(conversation.id)}
              className={cn(
                "block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-muted",
                conversation.id === conversationId && "bg-muted font-medium",
              )}
            >
              {conversation.title ?? "Untitled"}
            </button>
          ))}
        </nav>
        <div className="border-t p-3 text-xs text-muted-foreground">
          {principal.dept} · {principal.role}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {visible.length === 0 && (
            <p className="pt-20 text-center text-sm text-muted-foreground">
              Ask a question about company policy, teams, or tooling.
            </p>
          )}
          {visible.map((message, index) => (
            <div
              key={index}
              className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}
            >
              <div
                className={cn(
                  "max-w-[80%] rounded-lg px-4 py-2 text-sm",
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "border bg-card",
                )}
              >
                <p className="whitespace-pre-wrap">{message.content || "…"}</p>
                {message.role === "assistant" &&
                  ((message.sources && message.sources.length > 0) || message.sql) && (
                    <SourcePanel
                      sources={message.sources ?? []}
                      sql={message.sql}
                      traceId={message.traceId}
                    />
                  )}
              </div>
            </div>
          ))}
        </div>

        <form
          className="flex gap-2 border-t p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about parental leave, expenses, laptop setup…"
            className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <Button type="submit" disabled={busy || !input.trim()}>
            <Send className="h-4 w-4" />
            Send
          </Button>
        </form>
      </main>
    </div>
  );
}
