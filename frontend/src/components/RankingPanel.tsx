import {
  COMPONENT_LABELS,
  COMPONENT_ORDER,
  SELECTION_LABELS,
  formatRatio,
} from "../lib/format";
import type { DataQualityEntry, FundEvaluation, ScoreComponent } from "../types/api";
import { EvidenceBadge } from "./EvidenceBadge";

interface RankingPanelProps {
  funds: FundEvaluation[];
  weights: Record<string, number>;
}

const SELECTED = new Set(["SELECTED_PREFERENCE_PASS", "SELECTED_RANK_PASS"]);

export function RankingPanel({ funds, weights }: RankingPanelProps) {
  const eligible = funds.filter((fund) => fund.eligible);
  const shortlist = eligible.filter((fund) => fund.selection_reason && SELECTED.has(fund.selection_reason));
  const notSelected = eligible.filter(
    (fund) => !fund.selection_reason || !SELECTED.has(fund.selection_reason),
  );

  return (
    <div className="space-y-6">
      <RankingTable
        title="Shortlist"
        description="Eligible funds selected by the deterministic shortlist rules, in rank order."
        funds={shortlist}
        weights={weights}
        empty="No fund was shortlisted."
      />
      <RankingTable
        title="Eligible but not selected"
        description="Passed every screen but did not fit the shortlist."
        funds={notSelected}
        weights={weights}
        empty="Every eligible fund was shortlisted."
      />
    </div>
  );
}

function RankingTable({
  title,
  description,
  funds,
  weights,
  empty,
}: {
  title: string;
  description: string;
  funds: FundEvaluation[];
  weights: Record<string, number>;
  empty: string;
}) {
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold text-slate-100">
          {title} <span className="font-normal text-slate-500">({funds.length})</span>
        </h2>
        <p className="text-xs text-slate-400">{description}</p>
      </div>
      {funds.length === 0 ? (
        <p className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-400">
          {empty}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Rank</th>
                <th className="px-3 py-2">Fund</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Selection</th>
                <th className="px-3 py-2">Score</th>
                {COMPONENT_ORDER.map((name) => (
                  <th key={name} className="px-3 py-2">
                    {COMPONENT_LABELS[name] ?? name}
                    <span className="ml-1 font-mono normal-case text-slate-500">{weights[name]}%</span>
                  </th>
                ))}
                <th className="px-3 py-2">Data quality</th>
              </tr>
            </thead>
            <tbody>
              {funds.map((fund) => (
                <tr key={fund.fund_id} className="border-t border-slate-800 align-top">
                  <td className="px-3 py-2 font-mono text-slate-100">{fund.rank ?? "—"}</td>
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs text-cyan-200">{fund.fund_id}</div>
                    <div className="text-slate-200">{fund.fund_name}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-300">{fund.strategy}</td>
                  <td className="px-3 py-2">
                    <div className="text-slate-200">
                      {fund.selection_reason ? SELECTION_LABELS[fund.selection_reason] : "—"}
                    </div>
                    {fund.selection_detail && (
                      <div className="mt-0.5 text-xs text-slate-500">{fund.selection_detail}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-100">
                    {fund.total_score === null ? "—" : fund.total_score.toFixed(1)}
                  </td>
                  {COMPONENT_ORDER.map((name) => (
                    <ComponentCell key={name} component={fund.score_components?.[name]} />
                  ))}
                  <td className="px-3 py-2">
                    <DataQualityBadges entries={fund.data_quality} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ComponentCell({ component }: { component: ScoreComponent | undefined }) {
  if (!component) {
    return <td className="px-3 py-2 text-slate-500">—</td>;
  }
  const value =
    component.value === null ? "—" : Number.isInteger(component.value) ? String(component.value) : formatRatio(component.value);
  return (
    <td className="px-3 py-2 text-xs">
      <div className="font-mono text-slate-100">{component.points.toFixed(2)} pts</div>
      <div className="text-slate-500">
        p{component.percentile.toFixed(0)} · value {value}
      </div>
      {component.flag && (
        <div className="mt-0.5 inline-block rounded bg-amber-500/15 px-1.5 text-[10px] text-amber-100">
          {component.flag.replace(/_/g, " ")}
        </div>
      )}
    </td>
  );
}

export function DataQualityBadges({ entries }: { entries: DataQualityEntry[] }) {
  if (entries.length === 0) {
    return <span className="text-xs text-slate-500">None</span>;
  }
  return (
    <ul className="flex flex-col gap-1">
      {entries.map((entry) => (
        <li key={entry.evidence_id} className="flex flex-wrap items-center gap-1">
          <span
            title={entry.message}
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
              entry.severity === "error" ? "bg-red-500/20 text-red-100" : "bg-amber-500/20 text-amber-100"
            }`}
          >
            {entry.code}
          </span>
          <EvidenceBadge evidenceId={entry.evidence_id} />
        </li>
      ))}
    </ul>
  );
}
