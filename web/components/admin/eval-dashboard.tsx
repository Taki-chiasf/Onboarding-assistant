"use client";

import { useEffect, useState } from "react";

import { ChartPoint, MetricsChart } from "@/components/admin/metrics-chart";
import { Empty, ErrorNote, Flag, Loading, Section, Stat, Stats } from "@/components/admin/ui";
import { cn } from "@/lib/utils";

type RunPoint = {
  run_at: string;
  passed: boolean;
  strict: boolean;
  keyless: boolean;
  streak: number;
  regressions: string[];
  metrics: Record<string, number>;
};

type EvalHistory = {
  runs: RunPoint[];
  feedback: { real: number; synthetic: number };
  latest_sections: {
    router?: {
      accuracy: number;
      total: number;
      by_intent: Record<string, [number, number]>;
      ambiguous_boundary: [number, number];
    };
    sql?: { valid_rate: number; correct_rate: number; total: number };
    security?: { pass_rate: number; by_kind: Record<string, [number, number]> };
  } | null;
  gate_targets: Record<string, { target: number; direction: string }>;
};

const METRIC_LABELS: Record<string, string> = {
  router_accuracy: "Router accuracy",
  out_of_scope_refusal_rate: "Refusal rate",
  recall_at_5: "Recall@5",
  sql_valid_correct: "SQL valid+correct",
  judge_correctness: "Judge correctness",
  dont_know_rate: "Don't-know rate",
  rls_canary_pass_rate: "RLS canaries",
  injection_canary_pass_rate: "Injection canaries",
  p95_first_token_s: "p95 first token (s)",
  p95_answer_latency_s: "p95 answer (s)",
  median_cost_usd: "Median cost ($)",
};

function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name;
}

function isRate(name: string): boolean {
  return !name.includes("p95") && !name.includes("cost");
}

function formatMetric(name: string, value: number): string {
  if (name.includes("cost")) return `$${value.toFixed(4)}`;
  if (name.includes("p95")) return `${value.toFixed(2)}s`;
  return `${(value * 100).toFixed(1)}%`;
}

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function EvalPanel() {
  const [data, setData] = useState<EvalHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState("router_accuracy");

  useEffect(() => {
    let active = true;
    fetch("/api/admin/eval?limit=60", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: EvalHistory) => {
        if (!active) return;
        setData(body);
        const available = new Set(body.runs.flatMap((run) => Object.keys(run.metrics)));
        const last = body.runs.at(-1);
        setMetric((current) =>
          available.has(current) || !last
            ? current
            : (Object.keys(last.metrics)[0] ?? current)
        );
      })
      .catch(() => active && setError("Could not load the eval history."));
    return () => {
      active = false;
    };
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Loading />;

  const latest = data.runs.at(-1);
  const passRate = data.runs.length
    ? data.runs.filter((run) => run.passed).length / data.runs.length
    : 0;
  const availableMetrics = Array.from(
    new Set(data.runs.flatMap((run) => Object.keys(run.metrics)))
  );
  const target = data.gate_targets[metric];
  const points: ChartPoint[] = data.runs.map((run) => ({
    label: when(run.run_at),
    value: run.metrics[metric],
    passed: run.passed,
  }));
  const sections = data.latest_sections;

  return (
    <div className="space-y-10">
      <Stats>
        <Stat
          label="Latest run"
          value={latest ? (latest.passed ? "Passed" : "Failed") : "None"}
          hint={latest ? when(latest.run_at) : undefined}
        />
        <Stat label="Green streak" value={latest ? `${latest.streak} night(s)` : "0"} />
        <Stat label="Runs recorded" value={String(data.runs.length)} />
        <Stat label="Pass rate" value={`${(passRate * 100).toFixed(0)}%`} />
      </Stats>

      <Section title="Metric over time">
        <div className="p-3">
          <div className="flex flex-wrap gap-2">
            {availableMetrics.map((name) => (
              <button
                key={name}
                onClick={() => setMetric(name)}
                className={cn(
                  "rounded-full border px-3 py-1 text-[12px] transition-colors",
                  metric === name
                    ? "border-foreground/20 bg-secondary font-medium text-foreground"
                    : "text-muted-foreground hover:border-foreground/25 hover:text-foreground"
                )}
              >
                {metricLabel(name)}
              </button>
            ))}
          </div>
          <div className="mt-4">
            <MetricsChart
              points={points}
              target={target?.target}
              format={(value) => formatMetric(metric, value)}
            />
          </div>
          {target && (
            <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              {isRate(metric) ? "at least" : "at most"} {formatMetric(metric, target.target)} ·{" "}
              {metric === "median_cost_usd" ? "cost per answer" : "gate"}
            </p>
          )}
        </div>
      </Section>

      <Section title="Runs">
        {data.runs.length === 0 ? (
          <Empty>No nightly runs recorded yet.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                <th className="py-2 pr-4 font-normal">Run</th>
                <th className="py-2 pr-4 font-normal">Status</th>
                <th className="py-2 pr-4 font-normal">Mode</th>
                <th className="py-2 pr-4 text-right font-normal">Streak</th>
                <th className="py-2 font-normal">Regressions</th>
              </tr>
            </thead>
            <tbody>
              {[...data.runs].reverse().map((run) => (
                <tr key={run.run_at} className="border-t">
                  <td className="py-2 pr-4 font-mono text-[12px]">{when(run.run_at)}</td>
                  <td className="py-2 pr-4">
                    <Flag tone={run.passed ? "ok" : "error"}>
                      {run.passed ? "passed" : "failed"}
                    </Flag>
                  </td>
                  <td className="py-2 pr-4 text-xs text-muted-foreground">
                    {run.keyless ? "keyless smoke" : "keyed"}
                    {run.strict ? " · strict" : ""}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">{run.streak}</td>
                  <td className="py-2 font-mono text-[12px] text-muted-foreground">
                    {run.regressions.length > 0 ? run.regressions.join(", ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Feedback sources">
        <div className="grid grid-cols-2 gap-px bg-border">
          <div className="bg-background px-4 py-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Real ratings
            </p>
            <p className="mt-2 text-xl font-semibold tabular-nums">{data.feedback.real}</p>
            <p className="mt-1 text-xs text-muted-foreground">Thumbs from people.</p>
          </div>
          <div className="bg-background px-4 py-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Synthetic verdicts
            </p>
            <p className="mt-2 text-xl font-semibold tabular-nums">{data.feedback.synthetic}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Judge stand-in, active while real ratings are absent.
            </p>
          </div>
        </div>
      </Section>

      {sections && (
        <Section title="Latest breakdown">
          <div className="space-y-6 p-3">
            {sections.router && (
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  Router · {sections.router.total} cases
                </p>
                <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-3">
                  {Object.entries(sections.router.by_intent).map(([intent, [correct, total]]) => (
                    <li key={intent} className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="truncate text-muted-foreground">{intent}</span>
                      <span className="tabular-nums">
                        {correct}/{total}
                      </span>
                    </li>
                  ))}
                  <li className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="truncate text-muted-foreground">ambiguous boundary</span>
                    <span className="tabular-nums">
                      {sections.router.ambiguous_boundary[0]}/
                      {sections.router.ambiguous_boundary[1]}
                    </span>
                  </li>
                </ul>
              </div>
            )}
            {sections.sql && (
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  SQL · {sections.sql.total} replays
                </p>
                <p className="mt-2 text-sm text-muted-foreground">
                  valid {(sections.sql.valid_rate * 100).toFixed(1)}% · correct{" "}
                  {(sections.sql.correct_rate * 100).toFixed(1)}%
                </p>
              </div>
            )}
            {sections.security && (
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  Security canaries
                </p>
                <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-3">
                  {Object.entries(sections.security.by_kind).map(([kind, [passed, total]]) => (
                    <li key={kind} className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="truncate text-muted-foreground">{kind}</span>
                      <span className="tabular-nums">
                        {passed}/{total}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Section>
      )}
    </div>
  );
}
