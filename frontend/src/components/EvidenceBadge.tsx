interface EvidenceBadgeProps {
  evidenceId: string | null | undefined;
}

/** Evidence ID chip. Phase 4 wires the click to the audit drawer; for now it is inert. */
export function EvidenceBadge({ evidenceId }: EvidenceBadgeProps) {
  if (!evidenceId) {
    return null;
  }
  return (
    <button
      type="button"
      aria-disabled="true"
      title={`${evidenceId} (audit drawer arrives in Phase 4)`}
      onClick={(event) => event.preventDefault()}
      className="inline-flex max-w-full cursor-default items-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] leading-4 text-slate-400"
    >
      <span className="truncate">{evidenceId}</span>
    </button>
  );
}
