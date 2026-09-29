import type { ReactNode } from "react";
import { formatBps, formatMonthRange, formatRatio } from "../lib/format";
import type { FundEvaluation, FundMetrics } from "../types/api";
import { EvidenceBadge } from "./EvidenceBadge";

type MetricName = keyof FundMetrics;

const COLUMNS: Array<{ name: MetricName; label: string; render: (m: FundMetrics) => ReactNode }> = [
  { name: "months_of_history", label: "Months", render: (m) => String(m.months_of_history) },
  { name: "annualized_return_bps", label: "Ann. return", render: (m) => formatBps(m.annualized_return_bps as number) },
  { name: "volatility_bps", label: "Volatility", render: (m) => formatBps(m.volatility_bps as number) },
  { name: "sharpe", label: "Sharpe", render: (m) => formatRatio(m.sharpe as number) },
  { name: "max_drawdown_bps", label: "Max drawdown", render: (m) => formatBps(m.max_drawdown_bps as number) },
  {
    name: "correlation",
    label: "Correlation",
    render: (m) => `${formatRatio(m.correlation as number)} vs ${m.benchmark}`,
  },
  {
    name: "excess_return_bps",
    label: "Excess vs bmk",
    render: (m) => formatBps(m.excess_return_bps as number, { signed: true }),
  },
  {
    name: "target_gap_bps",
    label: "Target gap",
    render: (m) => formatBps(m.target_gap_bps as number, { signed: true }),
  },
];

export function FundMetricsTable({ funds }: { funds: FundEvaluation[] }) {
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold text-slate-100">Metrics for every evaluated fund</h2>
        <p className="text-xs text-slate-400">
          Computed on each fund's own history. "—" means the metric could not be verified; hover
          for the reason.
        </p>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2">Fund</th>
              <th className="px-3 py-2">Window</th>
              {COLUMNS.map((column) => (
                <th key={column.name} className="px-3 py-2">
                  {column.label}
                </th>
              ))}
              <th className="px-3 py-2">Risk-free used</th>
            </tr>
          </thead>
          <tbody>
            {funds.map((fund) => (
              <MetricsRow key={fund.fund_id} fund={fund} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MetricsRow({ fund }: { fund: FundEvaluation }) {
  const metrics = fund.metrics;
  const reasons = metrics?.unverifiable_reasons ?? {};
  const evidence = metrics?.metric_evidence ?? {};
  return (
    <tr className="border-t border-slate-800 align-top">
      <td className="px-3 py-2">
        <div className="font-mono text-xs text-cyan-200">{fund.fund_id}</div>
        <div className="text-slate-200">{fund.fund_name}</div>
        <div className="text-xs text-slate-500">
          {fund.eligible ? `Rank ${fund.rank}` : "Excluded"} · {fund.benchmark}
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-slate-300">
        {metrics?.window_start ? formatMonthRange(metrics.window_start, metrics.window_end) : "—"}
      </td>
      {COLUMNS.map((column) => {
        const value = metrics ? metrics[column.name] : null;
        if (!metrics || value === null || value === undefined) {
          const reason = reasons[column.name] ?? "Not computed for this fund.";
          return (
            <td key={column.name} className="px-3 py-2 text-slate-500">
              <span title={reason} className="cursor-help underline decoration-dotted underline-offset-2">
                —
              </span>
            </td>
          );
        }
        return (
          <td key={column.name} className="px-3 py-2">
            <div className="font-mono text-slate-100">{column.render(metrics)}</div>
            <div className="mt-1">
              <EvidenceBadge evidenceId={evidence[column.name]} />
            </div>
          </td>
        );
      })}
      <td className="px-3 py-2 text-xs text-slate-300">
        {metrics?.risk_free_annual_bps === null || metrics?.risk_free_annual_bps === undefined ? (
          "—"
        ) : (
          <>
            <div className="font-mono">{formatBps(metrics.risk_free_annual_bps)}</div>
            <div className="text-slate-500">{metrics.risk_free_source?.replace(/_/g, " ")}</div>
          </>
        )}
      </td>
    </tr>
  );
}
