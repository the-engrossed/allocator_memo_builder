import type { ReactNode } from "react";

const STEPS = [
  "Upload & Validation",
  "Mandate",
  "Analysis & Ranking",
  "IC Memo & Audit",
];

/**
 * available: prerequisites met and the step can be opened.
 * unlocked: prerequisites met, but the step is not built in this slice.
 * locked: prerequisites not met.
 */
export type StepAvailability =
  | { state: "available" }
  | { state: "unlocked"; hint: string }
  | { state: "locked"; hint: string };

interface AppShellProps {
  activeStep: number;
  steps: StepAvailability[];
  onSelectStep: (index: number) => void;
  children: ReactNode;
}

export function AppShell({ activeStep, steps, onSelectStep, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-slate-950">
      <header className="border-b border-slate-800 bg-slate-950/90 print:hidden">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-cyan-400">
              Allocator prototype
            </p>
            <h1 className="mt-1 text-xl font-semibold text-slate-50">IC Memo Workbench</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-400">
              Deterministic software owns the data, the math, and every displayed figure. The
              language model will only write cited narrative in a later step.
            </p>
          </div>
          <ol className="grid gap-2 sm:grid-cols-4">
            {STEPS.map((label, index) => {
              const step = steps[index] ?? { state: "locked", hint: "Locked" };
              const active = index === activeStep;
              const content = (
                <>
                  <span className="font-mono text-xs text-slate-400">0{index + 1}</span>
                  <div className="font-medium">{label}</div>
                  {step.state !== "available" && <div className="text-xs">{step.hint}</div>}
                </>
              );
              const tone = active
                ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-100"
                : step.state === "available"
                  ? "border-slate-700 text-slate-200 hover:border-slate-500"
                  : step.state === "unlocked"
                    ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-100"
                    : "border-slate-800 text-slate-500";
              return (
                <li key={label}>
                  {step.state === "available" ? (
                    <button
                      type="button"
                      aria-current={active ? "step" : undefined}
                      onClick={() => onSelectStep(index)}
                      className={`block h-full w-full rounded-lg border px-3 py-2 text-left text-sm transition ${tone}`}
                    >
                      {content}
                    </button>
                  ) : (
                    <div
                      aria-disabled="true"
                      className={`h-full rounded-lg border px-3 py-2 text-sm ${tone}`}
                    >
                      {content}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
