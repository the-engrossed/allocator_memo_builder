import { useEffect, useRef, type ReactNode } from "react";
import { formatBps, formatDateTime, formatMonthRange, formatObserved } from "../lib/format";
import type { EvidenceRecord } from "../types/api";

export type DrawerState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; record: EvidenceRecord | null };

interface AuditDrawerProps {
  evidenceId: string;
  state: DrawerState;
  onClose: () => void;
  onRetry: () => void;
}

const STATUS_TONE: Record<string, string> = {
  verified: "bg-emerald-500/15 text-emerald-100",
  unverifiable: "bg-amber-500/20 text-amber-100",
  invalid: "bg-red-500/20 text-red-100",
  missing: "bg-slate-700 text-slate-200",
};

export function AuditDrawer({ evidenceId, state, onClose, onRetry }: AuditDrawerProps) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
  }, [evidenceId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end print:hidden" role="presentation">
      <button type="button" aria-label="Close evidence" className="flex-1 cursor-default bg-slate-950/60" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-drawer-title"
        tabIndex={-1}
        className="h-full w-full max-w-md overflow-y-auto border-l border-slate-800 bg-slate-900 p-5 shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Evidence</p>
            <h2 id="audit-drawer-title" className="mt-1 break-all font-mono text-sm text-cyan-200">
              {evidenceId}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-2 py-1 text-sm text-slate-200 hover:border-slate-500"
          >
            Close
          </button>
        </div>

        <div className="mt-4">
          {state.status === "loading" && <p className="text-sm text-slate-400">Loading evidence…</p>}
          {state.status === "error" && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
              <span>{state.message}</span>
              <button type="button" onClick={onRetry} className="rounded border border-red-400/60 px-2 py-0.5">
                Retry
              </button>
            </div>
          )}
          {state.status === "ready" && state.record === null && (
            <p className="rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
              This evidence ID is not in the registry for this memo or run. The claim guard flags such
              citations.
            </p>
          )}
          {state.status === "ready" && state.record && <RecordDetails record={state.record} />}
        </div>
      </div>
    </div>
  );
}

function RecordDetails({ record }: { record: EvidenceRecord }) {
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5">
        <Row label="Type">{record.type.replace(/_/g, " ")}</Row>
        <Row label="Fund">{record.fund_id ?? "Run-wide"}</Row>
        <Row label="Label">{record.label}</Row>
        <Row label="Value">
          <span className="whitespace-pre-wrap font-mono text-slate-50">{record.display_value}</span>
        </Row>
        <Row label="Status">
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_TONE[record.verification_status] ?? ""}`}>
            {record.verification_status}
          </span>
        </Row>
      </dl>
      <section>
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Provenance</h3>
        <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5">
          <Provenance record={record} />
        </dl>
      </section>
    </div>
  );
}

function Provenance({ record }: { record: EvidenceRecord }) {
  const p = record.provenance;
  const text = (key: string) => formatObserved(p[key]);
  switch (record.type) {
    case "metric":
      return (
        <>
          <Row label="Formula"><code className="text-xs">{text("formula")}</code></Row>
          <Row label="Window">{formatMonthRange(p.window_start as string, p.window_end as string)}</Row>
          <Row label="Observations">{text("observations")}</Row>
          <Row label="Risk-free">
            {typeof p.risk_free_annual_bps === "number" ? formatBps(p.risk_free_annual_bps) : "—"} ({text("risk_free_source")})
          </Row>
          <Row label="Benchmark">{text("benchmark")}</Row>
          {p.overlap_months !== undefined && <Row label="Overlap">{text("overlap_months")} months</Row>}
          {p.target_return_bps !== undefined && (
            <Row label="Target">{formatBps(Number(p.target_return_bps))}</Row>
          )}
          <Row label="Ranking run"><span className="font-mono text-xs">{text("ranking_run_id")}</span></Row>
        </>
      );
    case "source_field":
      return (
        <>
          <Row label="Field">{text("field")}</Row>
          <Row label="Source row">{text("source_row")}</Row>
          <Row label="Raw CSV value">
            <span className="whitespace-pre-wrap font-mono text-xs">{String(p.raw_value ?? "")}</span>
          </Row>
          {p.untrusted_text === true && (
            <Row label="Note">Uploaded text, shown as data. The memo prompt marks it untrusted.</Row>
          )}
        </>
      );
    case "benchmark":
      return (
        <>
          <Row label="Provider">{text("provider")} / {text("series_id")}</Row>
          <Row label="State">{text("state")}</Row>
          <Row label="Retrieved">{formatDateTime(p.retrieved_at as string | null)}</Row>
          <Row label="Coverage">
            {p.coverage_start ? formatMonthRange(p.coverage_start as string, p.coverage_end as string) : "—"}
          </Row>
          <Row label="Message">{text("message")}</Row>
        </>
      );
    case "screen_result":
      return (
        <>
          <Row label="Code"><span className="font-mono text-xs">{record.evidence_id}</span></Row>
          <Row label="Screen">{text("screen")}</Row>
          <Row label="Result">{text("result")}</Row>
          <Row label="Observed">{text("observed")}</Row>
          <Row label="Threshold">{text("threshold")}</Row>
          <Row label="Reason">{text("reason")}</Row>
        </>
      );
    case "data_quality":
      return (
        <>
          <Row label="Code">{text("code")}</Row>
          <Row label="Severity">{text("severity")}</Row>
          <Row label="Field">{text("field")}</Row>
          <Row label="Source rows">{text("source_rows")}</Row>
        </>
      );
    case "selection":
      return (
        <>
          <Row label="Reason">{text("selection_reason")}</Row>
          <Row label="Detail">{text("selection_detail")}</Row>
          <Row label="Rank">{text("rank")}</Row>
          <Row label="Score">{text("total_score")}</Row>
        </>
      );
    default:
      return (
        <Row label="Details">
          <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(p, null, 2)}</pre>
        </Row>
      );
  }
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="break-words text-slate-200">{children}</dd>
    </>
  );
}
