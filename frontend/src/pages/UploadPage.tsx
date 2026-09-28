import { useState } from "react";
import { uploadAnalysis } from "../api/client";
import { UploadDropzone } from "../components/UploadDropzone";
import { ValidationIssuesTable } from "../components/ValidationIssuesTable";
import type { AnalysisResponse, AnalysisStatus } from "../types/api";

export function UploadPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      setAnalysis(await uploadAnalysis(file));
    } catch (cause) {
      setAnalysis(null);
      setError(cause instanceof Error ? cause.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <UploadDropzone disabled={busy} onFile={(file) => void handleFile(file)} />
      {busy && <p className="text-sm text-slate-400">Validating and storing the upload…</p>}
      {error && (
        <p className="rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
          {error}
        </p>
      )}
      {analysis && <AnalysisResult analysis={analysis} />}
    </div>
  );
}

function AnalysisResult({ analysis }: { analysis: AnalysisResponse }) {
  const canContinue = analysis.status !== "invalid";
  return (
    <div className="space-y-6">
      <section className="grid gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:grid-cols-4">
        <SummaryStat label="Status" value={statusLabel(analysis.status)} />
        <SummaryStat label="Rows" value={String(analysis.row_count)} />
        <SummaryStat label="Funds" value={String(analysis.fund_count)} />
        <SummaryStat label="Issues" value={String(analysis.issues.length)} />
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h2 className="text-sm font-semibold text-slate-100">Column mapping</h2>
        <p className="mt-1 text-xs text-slate-400">
          Canonical names were matched with the allowed aliases. No user mapping is applied.
        </p>
        <ul className="mt-3 grid gap-1 font-mono text-xs text-slate-300 sm:grid-cols-2">
          {Object.entries(analysis.column_mapping).map(([canonical, original]) => (
            <li key={canonical}>
              {canonical} ← {original}
            </li>
          ))}
        </ul>
      </section>

      <ValidationIssuesTable issues={analysis.issues} />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-100">Fund preview</h2>
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Fund</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Liquidity</th>
                <th className="px-3 py-2">Window</th>
                <th className="px-3 py-2">Obs</th>
                <th className="px-3 py-2">Blocked</th>
                <th className="px-3 py-2">Issues</th>
              </tr>
            </thead>
            <tbody>
              {analysis.funds.map((fund) => (
                <tr key={fund.fund_id} className="border-t border-slate-800">
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs text-cyan-200">{fund.fund_id}</div>
                    <div className="text-slate-200">{fund.fund_name}</div>
                  </td>
                  <td className="px-3 py-2">{fund.strategy || "—"}</td>
                  <td className="px-3 py-2">{fund.liquidity_frequency || "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-400">
                    {fund.first_period ?? "—"} → {fund.last_period ?? "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{fund.observations}</td>
                  <td className="px-3 py-2">{fund.analysis_blocked ? "Yes" : "No"}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {fund.issue_counts.error}e / {fund.issue_counts.warning}w / {fund.issue_counts.info}i
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <button
        type="button"
        disabled={!canContinue}
        className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        Continue to mandate
      </button>
      {!canContinue && (
        <p className="text-xs text-amber-200">
          This analysis is invalid. Fix the required columns or provide at least one valid
          observation before continuing.
        </p>
      )}
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-100">{value}</div>
    </div>
  );
}

function statusLabel(status: AnalysisStatus): string {
  switch (status) {
    case "invalid":
      return "Invalid";
    case "needs_review":
      return "Needs review";
    case "valid_with_warnings":
      return "Valid with warnings";
    case "valid":
      return "Valid";
  }
}
