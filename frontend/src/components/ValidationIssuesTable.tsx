import { useMemo, useState } from "react";
import type { IssueSeverity, ValidationIssue } from "../types/api";

interface ValidationIssuesTableProps {
  issues: ValidationIssue[];
}

const SEVERITIES: Array<IssueSeverity | "all"> = ["all", "error", "warning", "info"];

export function ValidationIssuesTable({ issues }: ValidationIssuesTableProps) {
  const funds = useMemo(() => {
    const names = new Set<string>();
    for (const issue of issues) {
      if (issue.fund_id) {
        names.add(issue.fund_id);
      }
    }
    return ["all", ...Array.from(names).sort()];
  }, [issues]);

  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>("all");
  const [fundId, setFundId] = useState("all");

  const visible = issues.filter((issue) => {
    if (severity !== "all" && issue.severity !== severity) {
      return false;
    }
    if (fundId !== "all" && issue.fund_id !== fundId) {
      return false;
    }
    return true;
  });

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-400">
          Severity
          <select
            className="mt-1 block rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as (typeof SEVERITIES)[number])}
          >
            {SEVERITIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Fund
          <select
            className="mt-1 block rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
            value={fundId}
            onChange={(event) => setFundId(event.target.value)}
          >
            {funds.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-500">{visible.length} issue(s)</p>
      </div>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2">Severity</th>
              <th className="px-3 py-2">Code</th>
              <th className="px-3 py-2">Fund</th>
              <th className="px-3 py-2">Field</th>
              <th className="px-3 py-2">Rows</th>
              <th className="px-3 py-2">Message</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((issue, index) => (
              <tr key={`${issue.code}-${issue.fund_id ?? "global"}-${index}`} className="border-t border-slate-800">
                <td className="px-3 py-2">
                  <SeverityMark severity={issue.severity} />
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-200">{issue.code}</td>
                <td className="px-3 py-2 font-mono text-xs">{issue.fund_id ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{issue.field ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs text-slate-400">
                  {issue.row_numbers.length ? issue.row_numbers.join(", ") : "—"}
                </td>
                <td className="px-3 py-2 text-slate-200">
                  {issue.message}
                  <RelatedFunds issue={issue} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RelatedFunds({ issue }: { issue: ValidationIssue }) {
  const related = issue.details.related_fund_ids;
  if (issue.code !== "FUND_ID_MISMATCH" || !Array.isArray(related) || related.length === 0) {
    return null;
  }
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
      <span className="text-slate-500">Related:</span>
      {related.map((fundId) => (
        <span key={String(fundId)} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-cyan-200">
          {String(fundId)}
        </span>
      ))}
    </div>
  );
}

function SeverityMark({ severity }: { severity: IssueSeverity }) {
  const className =
    severity === "error"
      ? "bg-red-500/20 text-red-200"
      : severity === "warning"
        ? "bg-amber-500/20 text-amber-100"
        : "bg-sky-500/20 text-sky-100";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{severity}</span>
  );
}
