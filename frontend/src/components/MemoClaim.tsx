import { splitMarkers } from "../lib/markers";
import type { EvidenceRecord, MemoClaim as Claim } from "../types/api";
import { useEvidenceDrawer } from "./EvidenceDrawerContext";

const TYPE_TONE: Record<Claim["claim_type"], string> = {
  quantitative: "bg-cyan-500/15 text-cyan-100",
  qualitative: "bg-slate-700 text-slate-200",
  judgment: "bg-violet-500/20 text-violet-100",
};

interface MemoClaimProps {
  claim: Claim;
  records: Map<string, EvidenceRecord>;
}

export function MemoClaim({ claim, records }: MemoClaimProps) {
  const flagged = claim.guard_status === "flagged";
  return (
    <li
      className={`rounded-lg border p-3 ${
        flagged ? "border-red-500/60 bg-red-950/30" : "border-slate-800 bg-slate-900"
      }`}
    >
      <p className="leading-7 text-slate-100">
        {splitMarkers(claim.text).map((segment, index) =>
          segment.kind === "text" ? (
            <span key={index}>{segment.text}</span>
          ) : (
            <MarkerChip key={index} evidenceId={segment.evidenceId} record={records.get(segment.evidenceId)} />
          ),
        )}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] print:hidden">
        <span className={`rounded px-1.5 py-0.5 ${TYPE_TONE[claim.claim_type]}`}>{claim.claim_type}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-300">
          {claim.fund_id ?? "multi-fund"}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 font-medium ${
            flagged ? "bg-red-500/25 text-red-100" : "bg-emerald-500/15 text-emerald-100"
          }`}
        >
          guard: {claim.guard_status}
        </span>
        <span className="font-mono text-slate-500">{claim.claim_id}</span>
      </div>
      {flagged && (
        <ul className="mt-2 space-y-1 text-xs text-red-100">
          {claim.guard_reasons.map((reason, index) => (
            <li key={`${reason.code}-${index}`}>
              <span className="font-mono">{reason.code}</span> · {reason.message}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function MarkerChip({ evidenceId, record }: { evidenceId: string; record: EvidenceRecord | undefined }) {
  const drawer = useEvidenceDrawer();
  const known = record !== undefined;
  const unverified = known && record.verification_status !== "verified";
  const tone = !known
    ? "border-red-500/70 bg-red-950/60 text-red-100"
    : unverified
      ? "border-amber-500/60 bg-amber-500/10 text-amber-100"
      : "border-cyan-500/40 bg-cyan-500/10 text-cyan-50";
  return (
    <button
      type="button"
      title={known ? `${record.label} · ${evidenceId}` : `Unknown evidence ID ${evidenceId}`}
      onClick={(event) => drawer?.open(evidenceId, event.currentTarget)}
      className={`mx-0.5 inline rounded border px-1.5 py-0.5 align-baseline text-sm hover:border-cyan-300 ${tone}`}
    >
      {known ? record.display_value : evidenceId}
    </button>
  );
}
