"use client";

import { useEffect, useState } from "react";

import { Empty, ErrorNote, Flag, Loading, Stat, Stats } from "@/components/admin/ui";

type IngestSource = {
  source_uri: string;
  source_type: string;
  chunks: number;
  last_ingested: string;
};

type IngestStatus = {
  total_chunks: number;
  total_sources: number;
  last_ingested: string | null;
  sources: IngestSource[];
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function IngestPanel() {
  const [data, setData] = useState<IngestStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/admin/ingest", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: IngestStatus) => active && setData(body))
      .catch(() => active && setError("Could not load the ingest status."));
    return () => {
      active = false;
    };
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Loading />;

  return (
    <div className="space-y-10">
      <Stats>
        <Stat label="Chunks indexed" value={data.total_chunks.toLocaleString("en-US")} />
        <Stat label="Sources" value={String(data.total_sources)} />
        <Stat label="Last ingestion" value={when(data.last_ingested)} />
        <Stat label="Corpus" value="synthetic" hint="Seeded sample documents" />
      </Stats>

      {data.sources.length === 0 ? (
        <Empty>The index is empty. Run the ingestion pipeline to populate it.</Empty>
      ) : (
        <div className="border-y">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                <th className="py-2 pr-4 pl-3 font-normal">Source</th>
                <th className="py-2 pr-4 font-normal">Type</th>
                <th className="py-2 pr-4 text-right font-normal">Chunks</th>
                <th className="py-2 pr-3 text-right font-normal">Last ingested</th>
              </tr>
            </thead>
            <tbody>
              {data.sources.map((source) => (
                <tr key={source.source_uri} className="border-t">
                  <td className="max-w-0 py-2 pr-4 pl-3">
                    <span className="block truncate font-mono text-[12px]">
                      {source.source_uri}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <Flag>{source.source_type}</Flag>
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">{source.chunks}</td>
                  <td className="py-2 pr-3 text-right text-xs text-muted-foreground">
                    {when(source.last_ingested)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
