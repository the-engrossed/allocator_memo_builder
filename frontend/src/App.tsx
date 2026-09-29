import { useCallback, useEffect, useState } from "react";
import { getMandate } from "./api/client";
import { AppShell, type StepAvailability } from "./components/AppShell";
import { AnalysisPage } from "./pages/AnalysisPage";
import { MandatePage } from "./pages/MandatePage";
import { UploadPage } from "./pages/UploadPage";
import type { AnalysisResponse } from "./types/api";

const UPLOAD_STEP = 0;
const MANDATE_STEP = 1;
const ANALYSIS_STEP = 2;

/** Stage 3 opens only when the API confirms a saved mandate, never from local state. */
type MandateCheck = "unknown" | "checking" | "saved" | "none" | "error";

export default function App() {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [activeStep, setActiveStep] = useState(UPLOAD_STEP);
  const [mandateCheck, setMandateCheck] = useState<MandateCheck>("unknown");
  const [mandateVersion, setMandateVersion] = useState(0);

  const analysisId = analysis?.analysis_id ?? null;
  const canOpenMandate = analysis !== null && analysis.status !== "invalid";

  useEffect(() => {
    if (!analysisId || !canOpenMandate) {
      setMandateCheck("unknown");
      return;
    }
    let cancelled = false;
    setMandateCheck("checking");
    getMandate(analysisId)
      .then((saved) => {
        if (!cancelled) {
          setMandateCheck(saved ? "saved" : "none");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMandateCheck("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, canOpenMandate, mandateVersion]);

  const canOpenAnalysis = canOpenMandate && mandateCheck === "saved";
  const step =
    activeStep === ANALYSIS_STEP && canOpenAnalysis
      ? ANALYSIS_STEP
      : activeStep >= MANDATE_STEP && canOpenMandate
        ? MANDATE_STEP
        : UPLOAD_STEP;

  const steps: StepAvailability[] = [
    { state: "available" },
    canOpenMandate
      ? { state: "available" }
      : { state: "locked", hint: "Upload a valid analysis first" },
    canOpenAnalysis
      ? { state: "available" }
      : {
          state: "locked",
          hint:
            mandateCheck === "checking"
              ? "Checking the saved mandate…"
              : mandateCheck === "error"
                ? "Could not check the mandate"
                : "Save a mandate first",
        },
    { state: "locked", hint: "Locked until the memo slice" },
  ];

  function handleAnalysis(next: AnalysisResponse | null) {
    setAnalysis(next);
    setActiveStep(UPLOAD_STEP);
  }

  const handleMandatePersisted = useCallback(() => setMandateVersion((value) => value + 1), []);

  return (
    <AppShell activeStep={step} steps={steps} onSelectStep={setActiveStep}>
      {step === ANALYSIS_STEP && analysis ? (
        <AnalysisPage key={analysis.analysis_id} analysis={analysis} />
      ) : step === MANDATE_STEP && analysis ? (
        <MandatePage
          key={analysis.analysis_id}
          analysis={analysis}
          onMandatePersisted={handleMandatePersisted}
        />
      ) : (
        <UploadPage
          analysis={analysis}
          onAnalysis={handleAnalysis}
          onContinue={() => setActiveStep(MANDATE_STEP)}
        />
      )}
    </AppShell>
  );
}
