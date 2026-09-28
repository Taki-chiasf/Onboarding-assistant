"use client";

import { useCallback, useEffect, useState } from "react";

import { Empty, ErrorNote, Flag, Loading, Section, Stat, Stats } from "@/components/admin/ui";
import { cn } from "@/lib/utils";

type DayCost = { day: string; tokens: number; cost_usd: string };
type UserCost = { user_id: string; tokens: number; cost_usd: string };
type ModelCost = { model: string; tokens_in: number; tokens_out: number; cost_usd: string };

type CostSummary = {
  window_days: number;
  daily_token_budget: number;
  daily_cost_alert_usd: number;
  days: DayCost[];
  users: UserCost[];
  models: ModelCost[];
};

const WINDOWS = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

function usd(value: string | number): string {
  return `$${Number(value).toFixed(4)}`;
}

function tokens(value: number): string {
  return value.toLocaleString("en-US");
}

export function CostPanel() {
  const [days, setDays] = useState(1);
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (window: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/admin/cost?days=${window}`, { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`cost request failed: ${res.status}`);
      }
      setData((await res.json()) as CostSummary);
    } catch {
      setError("Could not load the cost dashboard.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const totalTokens = data?.days.reduce((sum, row) => sum + row.tokens, 0) ?? 0;
  const totalCost = data?.days.reduce((sum, row) => sum + Number(row.cost_usd), 0) ?? 0;
  const budget = data?.daily_token_budget ?? 0;
  const alertThreshold = data?.daily_cost_alert_usd ?? 0;

  return (
    <div>
      <div className="flex items-center gap-2">
        {WINDOWS.map((window) => (
          <button
            key={window.days}
            onClick={() => setDays(window.days)}
            className={cn(
              "relative rounded-full border px-4 py-1.5 text-[13px] transition-colors",
              days === window.days
                ? "border-foreground/20 bg-secondary font-medium text-foreground"
                : "text-muted-foreground hover:border-foreground/25 hover:text-foreground"
            )}
          >
            {window.label}
            {days === window.days && (
              <span aria-hidden className="bg-ramp absolute inset-x-4 -bottom-px h-px" />
            )}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-8">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <div className="mt-8">
        <Stats>
          <Stat label="Tokens" value={tokens(totalTokens)} />
          <Stat label="Spend" value={usd(totalCost)} />
          <Stat label="Daily budget" value={budget > 0 ? `${tokens(budget)} tok` : "off"} />
          <Stat label="Alert above" value={alertThreshold > 0 ? usd(alertThreshold) : "off"} />
        </Stats>
      </div>

      {loading && !data ? (
        <Loading />
      ) : data ? (
        <div className="mt-10 space-y-10">
          <Section title="By day">
            {data.days.length === 0 ? (
              <Empty>No usage recorded yet.</Empty>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="py-2 pr-4 font-normal">Day</th>
                    <th className="py-2 pr-4 text-right font-normal">Tokens</th>
                    <th className="py-2 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.days.map((row) => (
                    <tr key={row.day} className="border-t">
                      <td className="py-2 pr-4 font-mono text-[13px]">{row.day}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{tokens(row.tokens)}</td>
                      <td className="py-2 text-right tabular-nums">{usd(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="By user">
            {data.users.length === 0 ? (
              <Empty>No usage recorded yet.</Empty>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="py-2 pr-4 font-normal">User</th>
                    <th className="py-2 pr-4 text-right font-normal">Tokens</th>
                    <th className="py-2 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((row) => {
                    const overBudget =
                      data.window_days === 1 && budget > 0 && row.tokens >= budget;
                    const overAlert = alertThreshold > 0 && Number(row.cost_usd) >= alertThreshold;
                    return (
                      <tr key={row.user_id} className="border-t">
                        <td className="py-2 pr-4">
                          <span className="flex items-center gap-2">
                            <span className="truncate font-mono text-[13px]">{row.user_id}</span>
                            {overBudget && <Flag tone="error">over budget</Flag>}
                            {!overBudget && overAlert && <Flag tone="warn">alert</Flag>}
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">{tokens(row.tokens)}</td>
                        <td className="py-2 text-right tabular-nums">{usd(row.cost_usd)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="By model">
            {data.models.length === 0 ? (
              <Empty>No usage recorded yet.</Empty>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="py-2 pr-4 font-normal">Model</th>
                    <th className="py-2 pr-4 text-right font-normal">In</th>
                    <th className="py-2 pr-4 text-right font-normal">Out</th>
                    <th className="py-2 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.models.map((row) => (
                    <tr key={row.model} className="border-t">
                      <td className="py-2 pr-4 font-mono text-[13px]">{row.model}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{tokens(row.tokens_in)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{tokens(row.tokens_out)}</td>
                      <td className="py-2 text-right tabular-nums">{usd(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </div>
      ) : null}
    </div>
  );
}
