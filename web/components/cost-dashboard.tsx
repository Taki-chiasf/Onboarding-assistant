"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { LogoutButton } from "@/components/logout-button";
import { PixelMark } from "@/components/pixel-mark";
import { cn } from "@/lib/utils";

type Principal = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

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

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="px-1 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {title}
      </h2>
      <div className="mt-3 border-y">{children}</div>
    </section>
  );
}

export function CostDashboard({ principal }: { principal: Principal }) {
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
    <div className="min-h-dvh">
      <div className="mx-auto w-full max-w-4xl px-4 py-10 md:px-6">
        <header className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <PixelMark className="h-6 w-6" assemble={false} />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold tracking-tight">Cost</h1>
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                Spend, tokens, and the daily budget
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
              Chat
            </Link>
            <LogoutButton />
          </div>
        </header>

        <div className="mt-10 flex items-center gap-2">
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
          <p className="mt-8 border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="mt-8 grid grid-cols-2 gap-px overflow-hidden border bg-border md:grid-cols-4">
          <Stat label="Tokens" value={tokens(totalTokens)} />
          <Stat label="Spend" value={usd(totalCost)} />
          <Stat label="Daily budget" value={budget > 0 ? `${tokens(budget)} tok` : "off"} />
          <Stat
            label="Alert above"
            value={alertThreshold > 0 ? usd(alertThreshold) : "off"}
          />
        </div>

        {loading && !data ? (
          <p className="mt-8 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            Loading
          </p>
        ) : data ? (
          <div className="mt-10 space-y-10">
            <Section title="By day">
              {data.days.length === 0 ? (
                <Empty />
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
                <Empty />
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
                      const overAlert =
                        alertThreshold > 0 && Number(row.cost_usd) >= alertThreshold;
                      return (
                        <tr key={row.user_id} className="border-t">
                          <td className="py-2 pr-4">
                            <span className="flex items-center gap-2">
                              <span className="truncate font-mono text-[13px]">
                                {row.user_id}
                              </span>
                              {overBudget && <Flag>over budget</Flag>}
                              {!overBudget && overAlert && <Flag>alert</Flag>}
                            </span>
                          </td>
                          <td className="py-2 pr-4 text-right tabular-nums">
                            {tokens(row.tokens)}
                          </td>
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
                <Empty />
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
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {tokens(row.tokens_in)}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {tokens(row.tokens_out)}
                        </td>
                        <td className="py-2 text-right tabular-nums">{usd(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          </div>
        ) : null}

        <p className="mt-10 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          {principal.email} · {principal.dept} · {principal.role}
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-background px-4 py-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold tabular-nums tracking-tight">{value}</p>
    </div>
  );
}

function Flag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-destructive/25 bg-destructive/5 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-destructive">
      {children}
    </span>
  );
}

function Empty() {
  return (
    <p className="py-6 text-sm text-muted-foreground">No usage recorded yet.</p>
  );
}
