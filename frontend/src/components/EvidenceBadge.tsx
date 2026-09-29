import { useEvidenceDrawer } from "./EvidenceDrawerContext";

interface EvidenceBadgeProps {
  evidenceId: string | null | undefined;
}

/** Evidence ID chip; opens the audit drawer when the page provides one. */
export function EvidenceBadge({ evidenceId }: EvidenceBadgeProps) {
  const drawer = useEvidenceDrawer();
  if (!evidenceId) {
    return null;
  }
  const interactive = drawer !== null;
  return (
    <button
      type="button"
      aria-disabled={interactive ? undefined : true}
      title={interactive ? `Open evidence ${evidenceId}` : evidenceId}
      onClick={(event) => {
        if (interactive) {
          drawer.open(evidenceId, event.currentTarget);
        }
      }}
      className={`inline-flex max-w-full items-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] leading-4 text-slate-400 ${
        interactive ? "hover:border-cyan-400/60 hover:text-cyan-200" : "cursor-default"
      }`}
    >
      <span className="truncate">{evidenceId}</span>
    </button>
  );
}
