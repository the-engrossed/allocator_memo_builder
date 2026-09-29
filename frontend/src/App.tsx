import { useCallback, useEffect, useState } from "react";
import { ApiError, getAnalysis, getLatestRankingRun, getMandate } from "./api/client";
import { AppShell, type StepAvailability } from "./components/AppShell";
import { AnalysisPage } from "./pages/AnalysisPage";
import { MandatePage } from "./pages/MandatePage";
import { MemoAuditPage } from "./pages/MemoAuditPage";
import { UploadPage } from "./pages/UploadPage";
import type { AnalysisResponse } from "./types/api";

const STAGES = ["upload", "mandate", "analysis", "memo"] as const;
const UPLOAD_STEP = 0;
const MANDATE_STEP = 1;
const ANALYSIS_STEP = 2;
const MEMO_STEP = 3;

/** Gates come from the API, never from local state: a saved mandate, then a ranking run. */
type Check<T> = { status: "unknown" | "checking" | "none" | "error" } | { status: "ready"; value: T };
type Boot = { status: "idle" } | { status: "restoring" } | { status: "not_found"; id: string } | { status: "error"; message: string };

function readUrl(): { analysisId: string | null; stage: number | null } {
  const params = new URLSearchParams(window.location.search);
  const stage = STAGES.indexOf((params.get("stage") ?? "") as (typeof STAGES)[number]);
  return { analysisId: params.get("analysis"), stage: stage >= 0 ? stage : null };
}

function writeUrl(analysisId: string | null, step: number) {
  const params = new URLSearchParams();
  if (analysisId) {
    params.set("analysis", analysisId);
    params.set("stage", STAGES[step] ?? "upload");
  }
  const search = params.toString();
  const next = `${window.location.pathname}${search ? `?${search}` : ""}`;
  if (next !== `${window.location.pathname}${window.location.search}`) {
    window.history.replaceState(null, "", next);
  }
}

export default function App() {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [boot, setBoot] = useState<Boot>(() => (readUrl().analysisId ? { status: "restoring" } : { status: "idle" }));
  const [bootAttempt, setBootAttempt] = useState(0);
  const [activeStep, setActiveStep] = useState(UPLOAD_STEP);
  const [requestedStep, setRequestedStep] = useState<number | null>(() => readUrl().stage);
  const [mandate, setMandate] = useState<Check<true>>({ status: "unknown" });
  const [run, setRun] = useState<Check<string>>({ status: "unknown" });
  const [mandateVersion, setMandateVersion] = useState(0);
  const [runVersion, setRunVersion] = useState(0);

  const analysisId = analysis?.analysis_id ?? null;
  const canOpenMandate = analysis !== null && analysis.status !== "invalid";

  useEffect(() => {
    const { analysisId: restoreId } = readUrl();
    if (!restoreId || boot.status !== "restoring") {
      return;
    }
    let cancelled = false;
    getAnalysis(restoreId)
      .then((restored) => {
        if (!cancelled) {
          setAnalysis(restored);
          setBoot({ status: "idle" });
        }
      })
      .catch((cause: unknown) => {
        if (cancelled) {
          return;
        }
        if (cause instanceof ApiError && (cause.status === 404 || cause.status === 422)) {
          setBoot({ status: "not_found", id: restoreId });
        } else {
          setBoot({ status: "error", message: cause instanceof Error ? cause.message : "Could not load the analysis." });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [boot.status, bootAttempt]);

  useEffect(() => {
    if (!analysisId || !canOpenMandate) {
      setMandate({ status: "unknown" });
      return;
    }
    let cancelled = false;
    setMandate({ status: "checking" });
    getMandate(analysisId)
      .then((saved) => !cancelled && setMandate(saved ? { status: "ready", value: true } : { status: "none" }))
      .catch(() => !cancelled && setMandate({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [analysisId, canOpenMandate, mandateVersion]);

  const mandateSaved = mandate.status === "ready";
  useEffect(() => {
    if (!analysisId || !mandateSaved) {
      setRun({ status: mandate.status === "checking" ? "checking" : "unknown" });
      return;
    }
    let cancelled = false;
    setRun({ status: "checking" });
    getLatestRankingRun(analysisId)
      .then((latest) => !cancelled && setRun(latest ? { status: "ready", value: latest.run_id } : { status: "none" }))
      .catch(() => !cancelled && setRun({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [analysisId, mandateSaved, mandate.status, runVersion]);

  const runId = run.status === "ready" ? run.value : null;
  const available = [true, canOpenMandate, canOpenMandate && mandateSaved, canOpenMandate && mandateSaved && runId !== null];
  const furthest = available.lastIndexOf(true);
  const resolved = (status: string) => status === "ready" || status === "none" || status === "error";
  const mandateResolved = !canOpenMandate || resolved(mandate.status);
  const runResolved = mandateSaved ? resolved(run.status) : mandateResolved;
  const settled = boot.status === "idle" && mandateResolved && runResolved;

  useEffect(() => {
    if (requestedStep === null || !settled || !analysis) {
      return;
    }
    setActiveStep(Math.min(requestedStep, furthest));
    setRequestedStep(null);
  }, [requestedStep, settled, analysis, furthest]);

  const step = available[activeStep] ? activeStep : Math.min(activeStep, furthest);

  useEffect(() => {
    if (boot.status === "idle" && requestedStep === null) {
      writeUrl(analysisId, step);
    }
  }, [analysisId, step, boot.status, requestedStep]);

  function hint(check: Check<unknown>, locked: string): StepAvailability {
    if (check.status === "checking") {
      return { state: "locked", hint: "Checking…" };
    }
    if (check.status === "error") {
      return { state: "locked", hint: "Could not check the API" };
    }
    return { state: "locked", hint: locked };
  }

  const steps: StepAvailability[] = [
    { state: "available" },
    available[MANDATE_STEP] ? { state: "available" } : { state: "locked", hint: "Upload a valid analysis first" },
    available[ANALYSIS_STEP] ? { state: "available" } : hint(mandate, "Save a mandate first"),
    available[MEMO_STEP] ? { state: "available" } : hint(run, "Run the analysis first"),
  ];

  function handleAnalysis(next: AnalysisResponse | null) {
    setAnalysis(next);
    setActiveStep(UPLOAD_STEP);
    setRequestedStep(null);
  }

  function backToUpload() {
    setAnalysis(null);
    setRequestedStep(null);
    setActiveStep(UPLOAD_STEP);
    setBoot({ status: "idle" });
    writeUrl(null, UPLOAD_STEP);
  }

  const handleMandatePersisted = useCallback(() => setMandateVersion((value) => value + 1), []);
  const handleRunCreated = useCallback(() => setRunVersion((value) => value + 1), []);

  let content;
  if (boot.status === "restoring" || (requestedStep !== null && !settled && boot.status === "idle" && analysis)) {
    content = <p className="text-sm text-slate-400">Restoring the analysis from the link…</p>;
  } else if (boot.status === "not_found") {
    content = (
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-6 text-sm text-amber-100">
        <h2 className="text-base font-semibold">Analysis not found</h2>
        <p className="mt-1">
          No analysis with ID <span className="font-mono">{boot.id}</span> exists on this server.
        </p>
        <button type="button" onClick={backToUpload} className="mt-3 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950">
          Back to upload
        </button>
      </div>
    );
  } else if (boot.status === "error") {
    content = (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
        <span>{boot.message}</span>
        <button
          type="button"
          onClick={() => {
            setBoot({ status: "restoring" });
            setBootAttempt((value) => value + 1);
          }}
          className="rounded-lg border border-red-400/60 px-3 py-1"
        >
          Retry
        </button>
        <button type="button" onClick={backToUpload} className="underline">
          Back to upload
        </button>
      </div>
    );
  } else if (step === MEMO_STEP && analysis && runId) {
    content = <MemoAuditPage key={runId} analysis={analysis} runId={runId} />;
  } else if (step === ANALYSIS_STEP && analysis) {
    content = <AnalysisPage key={analysis.analysis_id} analysis={analysis} onRunCreated={handleRunCreated} />;
  } else if (step === MANDATE_STEP && analysis) {
    content = (
      <MandatePage key={analysis.analysis_id} analysis={analysis} onMandatePersisted={handleMandatePersisted} />
    );
  } else {
    content = (
      <UploadPage analysis={analysis} onAnalysis={handleAnalysis} onContinue={() => setActiveStep(MANDATE_STEP)} />
    );
  }

  return (
    <AppShell activeStep={step} steps={steps} onSelectStep={setActiveStep}>
      {content}
    </AppShell>
  );
}
