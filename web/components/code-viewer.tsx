"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { EASE } from "@/lib/motion";

export type CodeFile = {
  source_uri: string;
  path: string;
  language: string;
  content: string;
  line_count: number;
  start_line: number | null;
  end_line: number | null;
  truncated: boolean;
};

/**
 * Read-only viewer for a cited source file. Opens as a drawer, highlights the
 * cited line range, and scrolls it into view. The backend serves the file only
 * when the caller can see it in the index.
 */
export function CodeViewer({
  sourceUri,
  startLine,
  endLine,
  anchor,
  onClose,
}: {
  sourceUri: string;
  startLine?: number | null;
  endLine?: number | null;
  anchor: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<CodeFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    const params = new URLSearchParams({ source_uri: sourceUri });
    if (startLine) params.set("start", String(startLine));
    if (endLine) params.set("end", String(endLine));
    fetch(`/api/code/file?${params.toString()}`, { cache: "no-store" })
      .then(async (res) => {
        const body = (await res.json().catch(() => null)) as
          | (CodeFile & { detail?: string })
          | null;
        if (!res.ok) {
          throw new Error(
            body?.detail === "file not found"
              ? "This file is not part of the indexed code corpus, or it is not visible to you."
              : (body?.detail ?? `Could not load the file (${res.status}).`)
          );
        }
        return body as CodeFile;
      })
      .then((body) => active && setData(body))
      .catch((cause: unknown) =>
        active
          ? setError(cause instanceof Error ? cause.message : "Could not load the file.")
          : undefined
      );
    return () => {
      active = false;
    };
  }, [sourceUri, startLine, endLine]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!data) return;
    const cited = listRef.current?.querySelector<HTMLElement>("[data-cited='start']");
    cited?.scrollIntoView({ block: "center" });
  }, [data]);

  const lines = data?.content.split("\n") ?? [];

  return (
    <AnimatePresence>
      <motion.div
        key="code-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <motion.aside
        key="code-drawer"
        initial={{ x: 24, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 24, opacity: 0 }}
        transition={{ duration: 0.2, ease: EASE }}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-3xl flex-col border-l bg-background shadow-lift"
        role="dialog"
        aria-label="Source file viewer"
      >
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b px-4">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Source file
            </p>
            <p className="truncate font-mono text-[12px]">{sourceUri.replace(/^file:/, "")}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {data && (
              <span className="rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {data.language}
              </span>
            )}
            <button
              type="button"
              aria-label="Close file viewer"
              onClick={onClose}
              className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto" ref={listRef}>
          {error ? (
            <p className="m-4 border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {error}
            </p>
          ) : !data ? (
            <p className="p-4 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              Loading file
            </p>
          ) : (
            <div className="min-w-max py-3 font-mono text-[12px] leading-[1.6]">
              {lines.map((line, index) => {
                const number = index + 1;
                const cited =
                  data.start_line !== null &&
                  number >= data.start_line &&
                  (data.end_line === null || number <= data.end_line);
                return (
                  <div
                    key={number}
                    data-cited={
                      cited && number === (data.start_line ?? -1) ? "start" : undefined
                    }
                    className={cn(
                      "flex border-l-2 border-transparent pr-6",
                      cited && "border-brand-vermilion bg-secondary"
                    )}
                  >
                    <span className="w-12 shrink-0 select-none pr-4 text-right text-[11px] text-muted-foreground/70 tabular-nums">
                      {number}
                    </span>
                    <span className="whitespace-pre">{line || " "}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <footer className="shrink-0 border-t px-4 py-3">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            <span className="truncate">{anchor}</span>
            {data && (
              <span>
                {data.line_count} line{data.line_count === 1 ? "" : "s"}
                {data.start_line !== null && ` · cited ${data.start_line}–${data.end_line ?? data.start_line}`}
              </span>
            )}
            {data?.truncated && <span>truncated</span>}
          </p>
        </footer>
      </motion.aside>
    </AnimatePresence>
  );
}
