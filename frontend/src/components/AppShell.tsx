import type { ReactNode } from "react";

const STEPS = [
  "Upload & Validation",
  "Mandate",
  "Analysis & Ranking",
  "IC Memo & Audit",
];

interface AppShellProps {
  activeStep: number;
  children: ReactNode;
}

export function AppShell({ activeStep, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-slate-950">
      <header className="border-b border-slate-800 bg-slate-950/90">
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
              const active = index === activeStep;
              const enabled = index <= activeStep;
              return (
                <li
                  key={label}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    active
                      ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-100"
                      : enabled
                        ? "border-slate-700 text-slate-200"
                        : "border-slate-800 text-slate-500"
                  }`}
                >
                  <span className="font-mono text-xs text-slate-400">0{index + 1}</span>
                  <div className="font-medium">{label}</div>
                  {!enabled && <div className="text-xs">Locked until this slice</div>}
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
