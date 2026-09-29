import { useCallback, useState } from "react";
import { AppShell, type StepAvailability } from "./components/AppShell";
import { MandatePage } from "./pages/MandatePage";
import { UploadPage } from "./pages/UploadPage";
import type { AnalysisResponse } from "./types/api";

const UPLOAD_STEP = 0;
const MANDATE_STEP = 1;

export default function App() {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [activeStep, setActiveStep] = useState(UPLOAD_STEP);
  const [mandateSaved, setMandateSaved] = useState(false);

  const canOpenMandate = analysis !== null && analysis.status !== "invalid";
  const showMandate = activeStep === MANDATE_STEP && canOpenMandate;

  const steps: StepAvailability[] = [
    { state: "available" },
    canOpenMandate
      ? { state: "available" }
      : { state: "locked", hint: "Upload a valid analysis first" },
    mandateSaved
      ? { state: "unlocked", hint: "Unlocked · built in the next slice" }
      : { state: "locked", hint: "Save a mandate first" },
    { state: "locked", hint: "Locked until ranking exists" },
  ];

  function handleAnalysis(next: AnalysisResponse | null) {
    setAnalysis(next);
    setMandateSaved(false);
  }

  const handleMandatePersisted = useCallback(() => setMandateSaved(true), []);

  return (
    <AppShell
      activeStep={showMandate ? MANDATE_STEP : UPLOAD_STEP}
      steps={steps}
      onSelectStep={setActiveStep}
    >
      {showMandate && analysis ? (
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
