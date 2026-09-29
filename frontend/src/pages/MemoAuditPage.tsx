import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, createMemo, getLatestMemo, getMemo, listMemos } from "../api/client";
import { EvidenceDrawerProvider } from "../components/EvidenceDrawerContext";
import { MemoAppendix } from "../components/MemoAppendix";
import { MemoClaim } from "../components/MemoClaim";
import { RankedShortlist } from "../components/RankedShortlist";
import { formatDateTime } from "../lib/format";
import type { AnalysisResponse, MemoResponse, MemoSection, MemoSummary } from "../types/api";

const TEMPLATE_REQUESTED = "template requested";
const DISCLOSURE =
  "Draft memo. Numbers come from the deterministic run; narrative is LLM-generated and checked " +
  "against cited evidence. Not investment advice.";
const SECTIONS: Array<[MemoSection, string]> = [
  ["executive_summary", "Executive summary"],
  ["recommendation", "Recommendation"],
  ["shortlist_rationale", "Shortlist rationale"],
  ["key_risks", "Key risks"],
];

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; value: T };
type PostState =
  | { status: "idle" }
  | { status: "pending"; mode: "auto" | "template" }
  | { status: "error"; message: string }
  | { status: "notice"; message: string };

interface MemoAuditPageProps {
  analysis: AnalysisResponse;
  runId: string;
}

export function MemoAuditPage({ analysis, runId }: MemoAuditPageProps) {
  const [memo, setMemo] = useState<Load<MemoResponse | null>>({ status: "loading" });
  const [revisions, setRevisions] = useState<MemoSummary[]>([]);
  const [post, setPost] = useState<PostState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  const refreshRevisions = useCallback(() => {
    listMemos(runId)
      .then(setRevisions)
      .catch(() => setRevisions([]));
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    setMemo({ status: "loading" });
    getLatestMemo(runId)
      .then((latest) => {
        if (!cancelled) {
          setMemo({ status: "ready", value: latest });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setMemo({ status: "error", message: message(cause, "Could not load the memo.") });
        }
      });
    refreshRevisions();
    return () => {
      cancelled = true;
    };
  }, [runId, attempt, refreshRevisions]);

  async function generate(mode: "auto" | "template") {
    setPost({ status: "pending", mode });
    try {
      const created = await createMemo(runId, mode);
      setMemo({ status: "ready", value: created });
      setPost({ status: "idle" });
      refreshRevisions();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.code === "MEMO_IN_PROGRESS") {
        setPost({ status: "notice", message: "Memo generation already in progress. Showing the latest revision." });
        setAttempt((value) => value + 1);
        return;
      }
      setPost({ status: "error", message: message(cause, "Memo generation failed.") });
    }
  }

  async function selectRevision(memoId: string) {
    setMemo({ status: "loading" });
    try {
      setMemo({ status: "ready", value: await getMemo(memoId) });
    } catch (cause) {
      setMemo({ status: "error", message: message(cause, "Could not load that revision.") });
    }
  }

  const pending = post.status === "pending";
  const current = memo.status === "ready" ? memo.value : null;
  const latestRevision = revisions.length ? revisions[revisions.length - 1]?.revision : undefined;

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 print:hidden">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">IC Memo &amp; Audit</h2>
          <p className="mt-1 text-sm text-slate-400">
            Every figure is a chip resolved from the memo's evidence snapshot. Click one to audit it.
          </p>
          <p className="mt-2 font-mono text-xs text-slate-500">
            {analysis.filename} · run {runId}
          </p>
        </div>
        {memo.status === "ready" && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => void generate("auto")}
              className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {memo.value ? "Regenerate" : "Generate IC memo"}
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => void generate("template")}
              className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Generate template memo (no LLM)
            </button>
            {current && (
              <button
                type="button"
                onClick={() => window.print()}
                className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200"
              >
                Print
              </button>
            )}
          </div>
        )}
      </section>

      {pending && (
        <p className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 print:hidden">
          {post.mode === "template" ? "Generating template memo…" : "Generating memo… this can take about a minute."}
        </p>
      )}
      {post.status === "notice" && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100 print:hidden">
          {post.message}
        </p>
      )}
      {post.status === "error" && (
        <Banner tone="error" message={`Generation failed: ${post.message}`} onRetry={() => void generate("auto")} />
      )}

      {memo.status === "loading" && <p className="text-sm text-slate-400">Loading memo…</p>}
      {memo.status === "error" && <Banner tone="error" message={memo.message} onRetry={() => setAttempt((v) => v + 1)} />}
      {memo.status === "ready" && memo.value === null && !pending && (
        <p className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-6 text-center text-sm text-slate-400">
          No memo for this ranking run yet. Use “Generate IC memo”.
        </p>
      )}

      {current && (
        <EvidenceDrawerProvider
          cacheKey={current.memo_id}
          load={() => Promise.resolve(current.evidence_snapshot)}
        >
          <MemoView
            memo={current}
            revisions={revisions}
            latestRevision={latestRevision}
            onSelectRevision={(id) => void selectRevision(id)}
          />
        </EvidenceDrawerProvider>
      )}

      <footer className="border-t border-slate-800 pt-4 text-xs text-slate-400">{DISCLOSURE}</footer>
    </div>
  );
}

function MemoView({
  memo,
  revisions,
  latestRevision,
  onSelectRevision,
}: {
  memo: MemoResponse;
  revisions: MemoSummary[];
  latestRevision: number | undefined;
  onSelectRevision: (memoId: string) => void;
}) {
  const records = useMemo(
    () => new Map(memo.evidence_snapshot.map((record) => [record.evidence_id, record])),
    [memo.evidence_snapshot],
  );
  const readOnly = latestRevision !== undefined && memo.revision !== latestRevision;
  const guard = memo.guard_summary;

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ModeLabel memo={memo} />
          <label className="text-xs text-slate-400 print:hidden">
            Revision{" "}
            <select
              value={memo.memo_id}
              onChange={(event) => onSelectRevision(event.target.value)}
              className="ml-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
            >
              {revisions.map((revision) => (
                <option key={revision.memo_id} value={revision.memo_id}>
                  Revision {revision.revision} · {revisionLabel(revision)} · {revision.guard_status}
                </option>
              ))}
              {!revisions.some((revision) => revision.memo_id === memo.memo_id) && (
                <option value={memo.memo_id}>Revision {memo.revision}</option>
              )}
            </select>
          </label>
        </div>
        {readOnly && (
          <p className="mt-2 text-xs text-amber-200">
            Viewing revision {memo.revision} (read-only). The latest is revision {latestRevision}.
          </p>
        )}
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
          <Item label="Memo ID" value={<span className="font-mono text-xs">{memo.memo_id}</span>} />
          <Item label="Revision" value={String(memo.revision)} />
          <Item label="Ranking run" value={<span className="font-mono text-xs">{memo.ranking_run_id}</span>} />
          <Item label="Generated" value={formatDateTime(memo.created_at)} />
          <Item label="Model" value={memo.model ?? "—"} />
          <Item
            label="Tokens (in / out / total)"
            value={
              memo.token_usage
                ? `${memo.token_usage.input_tokens ?? "—"} / ${memo.token_usage.output_tokens ?? "—"} / ${memo.token_usage.total_tokens ?? "—"}`
                : "—"
            }
          />
          <Item label="LLM attempts" value={memo.llm_attempts === null ? "—" : String(memo.llm_attempts)} />
          <Item label="Prompt" value={memo.prompt_version} />
        </dl>
        {memo.generation_mode === "template" && memo.fallback_reason && (
          <p className="mt-3 text-sm text-amber-100">
            Fallback reason: <span className="font-mono">{memo.fallback_reason}</span>
          </p>
        )}
      </section>

      <section
        className={`rounded-xl border p-4 text-sm ${
          guard.status === "clean"
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
            : "border-red-500/50 bg-red-950/40 text-red-100"
        }`}
      >
        <div className="font-semibold">
          Claim guard: {guard.status === "clean" ? "clean" : "flagged"}
        </div>
        <div className="mt-1">
          {guard.total} claims · {guard.ok} ok · {guard.flagged} flagged
        </div>
        {guard.memo_issues.length > 0 && (
          <ul className="mt-2 list-disc pl-5">
            {guard.memo_issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>
                <span className="font-mono text-xs">{issue.code}</span> · {issue.message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <RankedShortlist ranking={memo.llm_ranking} claims={memo.claims} records={records} />

      {SECTIONS.map(([section, title]) => {
        const claims = memo.claims.filter((claim) => claim.section === section);
        return (
          <section key={section} className="space-y-2">
            <h2 className="text-base font-semibold text-slate-100">{title}</h2>
            {claims.length === 0 ? (
              <p className="text-sm text-slate-500">No claims in this section.</p>
            ) : section === "shortlist_rationale" ? (
              groupByFund(claims).map(([fundId, fundClaims]) => (
                <div key={fundId} className="space-y-2">
                  <h3 className="font-mono text-sm text-cyan-200">{fundId}</h3>
                  <ul className="space-y-2">
                    {fundClaims.map((claim) => (
                      <MemoClaim key={claim.claim_id} claim={claim} records={records} />
                    ))}
                  </ul>
                </div>
              ))
            ) : (
              <ul className="space-y-2">
                {claims.map((claim) => (
                  <MemoClaim key={claim.claim_id} claim={claim} records={records} />
                ))}
              </ul>
            )}
          </section>
        );
      })}

      <MemoAppendix appendix={memo.appendix} />
    </div>
  );
}

function ModeLabel({ memo }: { memo: MemoResponse }) {
  const requested = memo.generation_mode === "template" && memo.fallback_reason === TEMPLATE_REQUESTED;
  const [label, tone] =
    memo.generation_mode === "llm"
      ? ["LLM-generated", "bg-violet-500/20 text-violet-100 border-violet-400/50"]
      : requested
        ? ["Template (requested)", "bg-slate-700 text-slate-100 border-slate-500"]
        : ["Template (LLM fallback)", "bg-amber-500/20 text-amber-100 border-amber-500/60"];
  return <span className={`rounded-full border px-3 py-1 text-sm font-semibold ${tone}`}>{label}</span>;
}

function revisionLabel(revision: MemoSummary): string {
  if (revision.generation_mode === "llm") {
    return revision.model ?? "LLM";
  }
  return revision.fallback_reason === TEMPLATE_REQUESTED ? "template (requested)" : "template (fallback)";
}

function groupByFund(claims: MemoResponse["claims"]): Array<[string, MemoResponse["claims"]]> {
  const groups = new Map<string, MemoResponse["claims"]>();
  for (const claim of claims) {
    const key = claim.rationale_fund_id ?? "—";
    groups.set(key, [...(groups.get(key) ?? []), claim]);
  }
  return [...groups.entries()];
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-1 text-slate-100">{value}</dd>
    </div>
  );
}

function Banner({ tone, message: text, onRetry }: { tone: "error"; message: string; onRetry: () => void }) {
  return (
    <div
      className={`flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm print:hidden ${
        tone === "error" ? "border-red-500/40 bg-red-950/40 text-red-100" : ""
      }`}
    >
      <span>{text}</span>
      <button type="button" onClick={onRetry} className="rounded-lg border border-red-400/60 px-3 py-1 font-medium">
        Retry
      </button>
    </div>
  );
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}
