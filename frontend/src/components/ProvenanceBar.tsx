import { STATE_LABELS, formatBps, formatDateTime, formatMonthRange } from "../lib/format";
import type { SeriesProvenance, SeriesState } from "../types/api";

const CARDS: Array<{ key: string; title: string }> = [
  { key: "SPY", title: "SPY · equity benchmark" },
  { key: "AGG", title: "AGG · credit benchmark" },
  { key: "risk_free", title: "Risk-free rate" },
];

const TONE: Record<SeriesState, string> = {
  live: "border-emerald-500/40 bg-emerald-500/5",
  cached: "border-emerald-500/30 bg-emerald-500/5",
  fallback: "border-amber-500/50 bg-amber-500/10",
  unavailable: "border-red-500/50 bg-red-950/40",
};

const PILL: Record<SeriesState, string> = {
  live: "bg-emerald-500/20 text-emerald-100",
  cached: "bg-emerald-500/15 text-emerald-200",
  fallback: "bg-amber-500/20 text-amber-100",
  unavailable: "bg-red-500/20 text-red-100",
};

export function ProvenanceBar({ provenance }: { provenance: Record<string, SeriesProvenance> }) {
  return (
    <section className="grid gap-3 sm:grid-cols-3" aria-label="Benchmark provenance">
      {CARDS.map(({ key, title }) => {
        const series = provenance[key];
        if (!series) {
          return (
            <div key={key} className="rounded-xl border border-slate-800 bg-slate-900 p-3 text-sm text-slate-400">
              {title}: not recorded for this run.
            </div>
          );
        }
        return (
          <div key={key} className={`rounded-xl border p-3 text-sm ${TONE[series.state]}`}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold text-slate-100">{title}</h3>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PILL[series.state]}`}>
                {STATE_LABELS[series.state]}
              </span>
            </div>
            <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-slate-500">Source</dt>
              <dd className="font-mono text-slate-200">
                {series.provider} / {series.series_id}
              </dd>
              <dt className="text-slate-500">Retrieved</dt>
              <dd className="text-slate-200">{formatDateTime(series.retrieved_at)}</dd>
              <dt className="text-slate-500">Coverage</dt>
              <dd className="text-slate-200">
                {series.coverage_start ? formatMonthRange(series.coverage_start, series.coverage_end) : "—"}
              </dd>
              {series.fallback_annual_bps !== undefined && (
                <>
                  <dt className="text-slate-500">Fallback rate</dt>
                  <dd className="text-slate-200">{formatBps(series.fallback_annual_bps)} annual</dd>
                </>
              )}
            </dl>
            <p className="mt-2 text-xs text-slate-400">{series.message}</p>
          </div>
        );
      })}
    </section>
  );
}
