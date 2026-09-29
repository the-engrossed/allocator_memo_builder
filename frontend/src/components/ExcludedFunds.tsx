import { formatObserved } from "../lib/format";
import type { FundEvaluation, ScreenResult } from "../types/api";
import { EvidenceBadge } from "./EvidenceBadge";
import { DataQualityBadges } from "./RankingPanel";

export function ExcludedFunds({ funds }: { funds: FundEvaluation[] }) {
  const excluded = funds.filter((fund) => !fund.eligible);
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold text-slate-100">
          Excluded <span className="font-normal text-slate-500">({excluded.length})</span>
        </h2>
        <p className="text-xs text-slate-400">
          A fund must pass every hard screen. Unverifiable counts as not passing.
        </p>
      </div>
      {excluded.length === 0 ? (
        <p className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-400">
          No fund was excluded.
        </p>
      ) : (
        <ul className="space-y-3">
          {excluded.map((fund) => (
            <ExcludedFund key={fund.fund_id} fund={fund} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ExcludedFund({ fund }: { fund: FundEvaluation }) {
  const blocking = fund.screens.filter((screen) => screen.result !== "pass");
  const passing = fund.screens.filter((screen) => screen.result === "pass");
  return (
    <li className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="font-mono text-xs text-cyan-200">{fund.fund_id}</span>{" "}
          <span className="text-slate-100">{fund.fund_name}</span>{" "}
          <span className="text-xs text-slate-500">· {fund.strategy}</span>
        </div>
        <DataQualityBadges entries={fund.data_quality} />
      </div>
      <ScreenTable screens={blocking} />
      {passing.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-slate-400">
            {passing.length} passing screen(s)
          </summary>
          <ScreenTable screens={passing} />
        </details>
      )}
    </li>
  );
}

const RESULT_TONE: Record<ScreenResult["result"], string> = {
  pass: "bg-emerald-500/15 text-emerald-100",
  fail: "bg-red-500/20 text-red-100",
  unverifiable: "bg-amber-500/20 text-amber-100",
};

function ScreenTable({ screens }: { screens: ScreenResult[] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="min-w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="py-1 pr-3">Screen</th>
            <th className="py-1 pr-3">Result</th>
            <th className="py-1 pr-3">Observed</th>
            <th className="py-1 pr-3">Threshold</th>
            <th className="py-1 pr-3">Reason</th>
            <th className="py-1">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {screens.map((screen) => (
            <tr key={screen.code} className="border-t border-slate-800 align-top">
              <td className="py-1.5 pr-3 font-mono text-slate-200">{screen.screen}</td>
              <td className="py-1.5 pr-3">
                <span className={`rounded px-1.5 py-0.5 font-medium ${RESULT_TONE[screen.result]}`}>
                  {screen.result}
                </span>
              </td>
              <td className="py-1.5 pr-3 font-mono text-slate-300">{formatObserved(screen.observed)}</td>
              <td className="py-1.5 pr-3 font-mono text-slate-300">{formatObserved(screen.threshold)}</td>
              <td className="py-1.5 pr-3 text-slate-300">{screen.reason}</td>
              <td className="py-1.5">
                <EvidenceBadge evidenceId={screen.code} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
