import type { ReactNode } from "react";
import { formatMonthRange } from "../lib/format";
import type { AppendixCell, EvidenceRecord, MemoAppendix as Appendix } from "../types/api";
import { useEvidenceDrawer } from "./EvidenceDrawerContext";

const METRIC_COLUMNS: Array<[string, string]> = [
  ["months_of_history", "Months"],
  ["annualized_return_bps", "Ann. return"],
  ["volatility_bps", "Volatility"],
  ["sharpe", "Sharpe"],
  ["max_drawdown_bps", "Max DD"],
  ["correlation", "Correlation"],
  ["excess_return_bps", "Excess"],
  ["target_gap_bps", "Target gap"],
];

export function MemoAppendix({ appendix }: { appendix: Appendix }) {
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-slate-100">Data appendix</h2>
        <p className="text-xs text-slate-400">
          Built deterministically from ranking run{" "}
          <span className="font-mono">{appendix.generated_from.ranking_run_id}</span> (policy{" "}
          {appendix.generated_from.policy_version}). Not written by the LLM.
        </p>
      </div>

      <Table title="Metrics" head={["Fund", "Window", ...METRIC_COLUMNS.map(([, label]) => label)]}>
        {appendix.metrics.map((row) => (
          <tr key={row.fund_id} className="border-t border-slate-800 align-top">
            <td className="px-2 py-1.5 font-mono text-cyan-200">
              {row.fund_id}
              <div className="text-[10px] text-slate-500">
                {row.eligible ? `rank ${row.rank}` : "excluded"} · {row.benchmark}
              </div>
            </td>
            <td className="px-2 py-1.5 text-slate-300">
              {row.window_start ? formatMonthRange(row.window_start, row.window_end) : "—"}
            </td>
            {METRIC_COLUMNS.map(([name]) => (
              <td key={name} className="px-2 py-1.5">
                <CellChip cell={row.metrics[name]} />
              </td>
            ))}
          </tr>
        ))}
      </Table>

      <Table title="Screens" head={["Fund", "Eligible", "Screen results"]}>
        {appendix.screens.map((row) => (
          <tr key={row.fund_id} className="border-t border-slate-800 align-top">
            <td className="px-2 py-1.5 font-mono text-cyan-200">{row.fund_id}</td>
            <td className="px-2 py-1.5 text-slate-300">{row.eligible ? "Yes" : "No"}</td>
            <td className="px-2 py-1.5">
              <div className="flex flex-wrap gap-1">
                {row.screens.map((cell, index) =>
                  cell ? (
                    <span key={cell.evidence_id ?? index} className="inline-flex items-center gap-1">
                      <span className="text-[10px] text-slate-500">{cell.screen}</span>
                      <CellChip cell={cell} />
                    </span>
                  ) : null,
                )}
              </div>
            </td>
          </tr>
        ))}
      </Table>

      <Table title="Selection" head={["Fund", "Rank", "Decision"]}>
        {appendix.selection.map((row) => (
          <tr key={row.fund_id} className="border-t border-slate-800">
            <td className="px-2 py-1.5 font-mono text-cyan-200">{row.fund_id}</td>
            <td className="px-2 py-1.5 font-mono text-slate-300">{row.rank ?? "—"}</td>
            <td className="px-2 py-1.5">
              <CellChip cell={row.evidence_id ? (row as AppendixCell) : undefined} />
            </td>
          </tr>
        ))}
      </Table>

      <Table title="Benchmarks" head={["Series", "State", "Value"]}>
        {appendix.benchmarks.map((record) => (
          <RecordRow key={record.evidence_id} record={record} state={String(record.provenance.state ?? "")} />
        ))}
      </Table>

      <Table title="Run warnings" head={["Warning", "", "Message"]}>
        {appendix.run_warnings.length === 0 ? (
          <tr>
            <td colSpan={3} className="px-2 py-1.5 text-slate-500">
              None for this run.
            </td>
          </tr>
        ) : (
          appendix.run_warnings.map((record) => <RecordRow key={record.evidence_id} record={record} state="" />)
        )}
      </Table>
    </section>
  );
}

function RecordRow({ record, state }: { record: EvidenceRecord; state: string }) {
  return (
    <tr className="border-t border-slate-800">
      <td className="px-2 py-1.5 text-slate-200">{record.label}</td>
      <td className="px-2 py-1.5 text-slate-300">{state}</td>
      <td className="px-2 py-1.5">
        <CellChip
          cell={{
            evidence_id: record.evidence_id,
            display_value: record.display_value,
            verification_status: record.verification_status,
          }}
        />
      </td>
    </tr>
  );
}

function CellChip({ cell }: { cell: AppendixCell | undefined }) {
  const drawer = useEvidenceDrawer();
  if (!cell) {
    return <span className="text-slate-500">—</span>;
  }
  if (!cell.evidence_id) {
    return (
      <span title={cell.reason ?? "Not computed"} className="cursor-help text-slate-500 underline decoration-dotted">
        —
      </span>
    );
  }
  const evidenceId = cell.evidence_id;
  const tone =
    cell.verification_status === "verified"
      ? "border-slate-700 text-slate-100"
      : "border-amber-500/60 text-amber-100";
  return (
    <button
      type="button"
      title={evidenceId}
      onClick={(event) => drawer?.open(evidenceId, event.currentTarget)}
      className={`rounded border bg-slate-950 px-1.5 py-0.5 text-left font-mono text-xs hover:border-cyan-400/60 ${tone}`}
    >
      {cell.display_value}
    </button>
  );
}

function Table({ title, head, children }: { title: string; head: string[]; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-900 uppercase tracking-wide text-slate-400">
            <tr>
              {head.map((label, index) => (
                <th key={`${label}-${index}`} className="px-2 py-1.5">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );
}
