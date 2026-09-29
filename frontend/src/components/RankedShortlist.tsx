import type { EvidenceRecord, LlmRanking, LlmRankingRow, MemoClaim as Claim } from "../types/api";
import { MemoClaim } from "./MemoClaim";

interface RankedShortlistProps {
  ranking: LlmRanking | null;
  claims: Claim[];
  records: Map<string, EvidenceRecord>;
}

const MOVE_TONE: Record<LlmRankingRow["move"], string> = {
  same: "bg-slate-800 text-slate-300",
  up: "bg-emerald-500/15 text-emerald-100",
  down: "bg-amber-500/15 text-amber-100",
  new: "bg-cyan-500/15 text-cyan-100",
  dropped: "bg-red-500/15 text-red-100",
  invalid_drop: "bg-red-500/25 text-red-100",
};

function moveLabel(row: LlmRankingRow): string {
  switch (row.move) {
    case "up":
      return `↑ ${row.delta}`;
    case "down":
      return `↓ ${Math.abs(row.delta ?? 0)}`;
    case "same":
      return "—";
    case "new":
      return "new";
    case "dropped":
      return "dropped";
    case "invalid_drop":
      return "invalid drop";
  }
}

export function RankedShortlist({ ranking, claims, records }: RankedShortlistProps) {
  const byId = new Map(claims.map((claim) => [claim.claim_id, claim]));
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-base font-semibold text-slate-100">Ranked shortlist</h2>
        <p className="text-sm text-slate-400">
          {ranking === null
            ? "This revision predates the LLM ranking; it follows the deterministic shortlist."
            : ranking.source === "llm"
              ? "LLM ranking (guard-checked) vs deterministic baseline."
              : "Deterministic baseline order (template memo; no LLM ranking)."}
        </p>
      </div>
      {ranking !== null && (
        <ol className="space-y-2">
          {[...ranking.entries, ...ranking.dropped].map((row, index) => {
            const claim = row.claim_id ? byId.get(row.claim_id) : undefined;
            return (
              <li
                key={`${row.fund_id}-${row.move}-${index}`}
                className="grid gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3 sm:grid-cols-[11rem_1fr]"
              >
                <div className="space-y-1 text-sm">
                  <div className="flex items-baseline gap-2">
                    <span className="text-lg font-semibold text-slate-50">
                      {row.llm_rank === null ? "—" : `#${row.llm_rank}`}
                    </span>
                    <span className="font-mono text-cyan-200">{row.fund_id}</span>
                  </div>
                  <div className="text-xs text-slate-400">
                    Baseline {row.baseline_rank === null ? (row.eligible ? "—" : "not eligible") : `#${row.baseline_rank}`}
                  </div>
                  <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${MOVE_TONE[row.move]}`}>
                    {moveLabel(row)}
                  </span>
                </div>
                {claim ? (
                  <ul>
                    <MemoClaim claim={claim} records={records} />
                  </ul>
                ) : (
                  <p className="self-center text-sm text-red-200">No rationale given for this change.</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
