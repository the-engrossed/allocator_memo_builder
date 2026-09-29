import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createRankingRun, getLatestRankingRun, getMandate } from "../api/client";
import { ExcludedFunds } from "../components/ExcludedFunds";
import { FundMetricsTable } from "../components/FundMetricsTable";
import { ProvenanceBar } from "../components/ProvenanceBar";
import { RankingPanel } from "../components/RankingPanel";
import { formatDateTime, shortHash } from "../lib/format";
import type { AnalysisResponse, RankingRunResponse } from "../types/api";

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

type PostState = { status: "idle" } | { status: "pending" } | { status: "error"; message: string };

const FOOTER =
  "Deterministic screening and baseline ranking (policy v1). Benchmarks from Yahoo Finance and " +
  "FRED with cached/snapshot fallback. Not investment advice.";

export function AnalysisPage({ analysis }: { analysis: AnalysisResponse }) {
  const analysisId = analysis.analysis_id;
  const [mandate, setMandate] = useState<Load<boolean>>({ status: "loading" });
  const [run, setRun] = useState<Load<RankingRunResponse | null>>({ status: "loading" });
  const [post, setPost] = useState<PostState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setMandate({ status: "loading" });
    setRun({ status: "loading" });
    getMandate(analysisId)
      .then(async (saved) => {
        if (cancelled) {
          return;
        }
        setMandate({ status: "ready", value: saved !== null });
        if (saved === null) {
          return;
        }
        try {
          const latest = await getLatestRankingRun(analysisId);
          if (!cancelled) {
            setRun({ status: "ready", value: latest });
          }
        } catch (cause) {
          if (!cancelled) {
            setRun({ status: "error", message: errorMessage(cause, "Could not load the latest run.") });
          }
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setMandate({ status: "error", message: errorMessage(cause, "Could not check the mandate.") });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  async function startRun() {
    setPost({ status: "pending" });
    try {
      const created = await createRankingRun(analysisId);
      setRun({ status: "ready", value: created });
      setPost({ status: "idle" });
    } catch (cause) {
      setPost({ status: "error", message: errorMessage(cause, "The ranking run failed.") });
    }
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Analysis &amp; Ranking</h2>
          <p className="mt-1 text-sm text-slate-400">
            Screens, scores, and shortlists are computed by the backend. This page only displays
            them.
          </p>
          <p className="mt-2 font-mono text-xs text-slate-500">
            {analysis.filename} · {analysisId}
          </p>
        </div>
        {mandate.status === "ready" && mandate.value && run.status === "ready" && (
          <button
            type="button"
            disabled={post.status === "pending"}
            onClick={() => void startRun()}
            className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            {post.status === "pending"
              ? "Running…"
              : run.value
                ? "Re-run"
                : "Run analysis & rank"}
          </button>
        )}
      </section>

      {post.status === "error" && (
        <ErrorBanner message={`Run failed: ${post.message}`} onRetry={() => void startRun()} />
      )}

      {mandate.status === "loading" && <Muted>Checking the saved mandate…</Muted>}
      {mandate.status === "error" && <ErrorBanner message={mandate.message} onRetry={retry} />}
      {mandate.status === "ready" && !mandate.value && (
        <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          No saved mandate for this analysis. Save one on the Mandate step before ranking.
        </p>
      )}

      {mandate.status === "ready" && mandate.value && (
        <>
          {run.status === "loading" && <Muted>Loading the latest ranking run…</Muted>}
          {run.status === "error" && <ErrorBanner message={run.message} onRetry={retry} />}
          {run.status === "ready" && run.value === null && (
            <p className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-6 text-center text-sm text-slate-400">
              No ranking run yet. Use “Run analysis &amp; rank” to screen and rank this universe
              against the saved mandate.
            </p>
          )}
          {run.status === "ready" && run.value && <RunView run={run.value} />}
        </>
      )}

      <footer className="border-t border-slate-800 pt-4 text-xs text-slate-500">{FOOTER}</footer>
    </div>
  );
}

function RunView({ run }: { run: RankingRunResponse }) {
  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-4">
          <HeaderItem label="Run ID" value={<span className="font-mono text-xs">{run.run_id}</span>} />
          <HeaderItem label="Policy" value={run.policy_version} />
          <HeaderItem label="Created" value={formatDateTime(run.created_at)} />
          <HeaderItem
            label="Mandate SHA-256"
            value={
              <span title={run.mandate_sha256} className="cursor-help font-mono text-xs">
                {shortHash(run.mandate_sha256)}
              </span>
            }
          />
        </dl>
      </section>

      {run.warnings.length > 0 && (
        <section className="space-y-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
          <h3 className="text-sm font-semibold text-amber-100">Run warnings</h3>
          <ul className="space-y-1 text-sm text-amber-100">
            {run.warnings.map((warning) => (
              <li key={warning.code}>
                <span className="font-mono text-xs">{warning.code}</span> · {warning.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <ProvenanceBar provenance={run.benchmark_provenance} />

      <section className="grid gap-3 sm:grid-cols-4">
        <Count label="Evaluated" value={run.summary.evaluated} />
        <Count label="Eligible" value={run.summary.eligible} />
        <Count label="Excluded" value={run.summary.excluded} />
        <Count label="Shortlisted" value={run.summary.shortlisted} />
      </section>

      <RankingPanel funds={run.funds} weights={run.score_weights} />
      <FundMetricsTable funds={run.funds} />
      <ExcludedFunds funds={run.funds} />
    </div>
  );
}

function HeaderItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-1 text-slate-100">{value}</dd>
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-mono text-2xl text-slate-50">{value}</div>
    </div>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-slate-400">{children}</p>;
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
      <span>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-lg border border-red-400/60 px-3 py-1 text-sm font-medium hover:bg-red-950/60"
      >
        Retry
      </button>
    </div>
  );
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}
