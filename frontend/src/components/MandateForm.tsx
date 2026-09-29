import type { FormEvent, ReactNode } from "react";
import {
  MANDATE_LIMITS,
  bpsToPercentText,
  parseInteger,
  type MandateDraft,
  type MandateDraftField,
  type MandateFieldErrors,
} from "../lib/mandateForm";
import { StrategyChips } from "./StrategyChips";

export type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; updatedAt: string }
  | { status: "error"; message: string };

export type TextDraftField = Exclude<MandateDraftField, "preferred_strategies">;

interface MandateFormProps {
  draft: MandateDraft;
  errors: MandateFieldErrors;
  strategyOptions: string[];
  universeStrategies: string[];
  saveState: SaveState;
  statusNote: ReactNode;
  onChange: (field: TextDraftField, value: string) => void;
  onToggleStrategy: (strategy: string) => void;
  onSubmit: () => void;
}

export function MandateForm({
  draft,
  errors,
  strategyOptions,
  universeStrategies,
  saveState,
  statusNote,
  onChange,
  onToggleStrategy,
  onSubmit,
}: MandateFormProps) {
  const saving = saveState.status === "saving";

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="space-y-6" noValidate onSubmit={handleSubmit}>
      <FormSection title="Return & fees">
        <TextField
          label="Target return"
          suffix="%"
          inputMode="decimal"
          value={draft.target_return_pct}
          error={errors.target_return_pct}
          disabled={saving}
          hint="Annual target, 0–100%. Up to two decimals; 0.01% = 1 bp."
          onChange={(value) => onChange("target_return_pct", value)}
        />
        <TextField
          label="Max management fee"
          suffix="bps"
          inputMode="numeric"
          value={draft.max_mgmt_fee_bps}
          error={errors.max_mgmt_fee_bps}
          disabled={saving}
          hint={bpsHint(draft.max_mgmt_fee_bps, MANDATE_LIMITS.max_mgmt_fee_bps)}
          onChange={(value) => onChange("max_mgmt_fee_bps", value)}
        />
        <TextField
          label="Max performance fee"
          suffix="bps"
          inputMode="numeric"
          value={draft.max_perf_fee_bps}
          error={errors.max_perf_fee_bps}
          disabled={saving}
          hint={bpsHint(draft.max_perf_fee_bps, MANDATE_LIMITS.max_perf_fee_bps)}
          onChange={(value) => onChange("max_perf_fee_bps", value)}
        />
      </FormSection>

      <FormSection title="Liquidity">
        <TextField
          label="Max notice period"
          suffix="days"
          inputMode="numeric"
          value={draft.max_notice_days}
          error={errors.max_notice_days}
          disabled={saving}
          hint="Whole days, 0–3650."
          onChange={(value) => onChange("max_notice_days", value)}
        />
        <TextField
          label="Max lockup"
          suffix="months"
          inputMode="numeric"
          value={draft.max_lockup_months}
          error={errors.max_lockup_months}
          disabled={saving}
          hint="Whole months, 0–120."
          onChange={(value) => onChange("max_lockup_months", value)}
        />
      </FormSection>

      <FormSection title="Strategy">
        <div className="sm:col-span-3">
          <FieldLabel>Preferred strategies</FieldLabel>
          <div className="mt-2">
            <StrategyChips
              options={strategyOptions}
              selected={draft.preferred_strategies}
              universe={universeStrategies}
              disabled={saving}
              onToggle={onToggleStrategy}
            />
          </div>
          {errors.preferred_strategies && <FieldError>{errors.preferred_strategies}</FieldError>}
        </div>
        <TextField
          label="Strategy concentration cap"
          suffix="%"
          inputMode="decimal"
          value={draft.strategy_concentration_cap_pct}
          error={errors.strategy_concentration_cap_pct}
          disabled={saving}
          hint="Maximum share of the shortlist per strategy, 0–100%. Up to two decimals."
          onChange={(value) => onChange("strategy_concentration_cap_pct", value)}
        />
      </FormSection>

      <FormSection title="Shortlist">
        <TextField
          label="Max candidates"
          inputMode="numeric"
          value={draft.max_candidates}
          error={errors.max_candidates}
          disabled={saving}
          hint="Whole number, 1–20."
          onChange={(value) => onChange("max_candidates", value)}
        />
      </FormSection>

      <div className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:flex-row sm:items-center sm:justify-between">
        <SaveStatus saveState={saveState} statusNote={statusNote} onRetry={onSubmit} />
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {saving ? "Saving…" : "Save mandate & continue"}
        </button>
      </div>
    </form>
  );
}

function SaveStatus({
  saveState,
  statusNote,
  onRetry,
}: {
  saveState: SaveState;
  statusNote: ReactNode;
  onRetry: () => void;
}) {
  switch (saveState.status) {
    case "saving":
      return <p className="text-sm text-slate-400">Saving the complete mandate…</p>;
    case "saved":
      return (
        <p className="text-sm text-emerald-200">
          Mandate saved <Timestamp iso={saveState.updatedAt} />. Analysis & Ranking is unlocked.
        </p>
      );
    case "error":
      return (
        <div className="flex flex-wrap items-center gap-3 text-sm text-red-100">
          <span className="rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2">
            Save failed: {saveState.message}
          </span>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-lg border border-red-400/60 px-3 py-1.5 text-sm font-medium text-red-100 hover:bg-red-950/60"
          >
            Retry save
          </button>
        </div>
      );
    case "idle":
      return <div className="text-sm text-slate-400">{statusNote}</div>;
  }
}

export function Timestamp({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} title={iso} className="font-mono text-xs">
      {new Date(iso).toLocaleString()}
    </time>
  );
}

function bpsHint(text: string, limits: { min: number; max: number }): string {
  const parsed = parseInteger(text, limits.min, limits.max);
  const range = `Whole basis points, ${limits.min}–${limits.max}.`;
  return parsed.ok ? `${range} = ${bpsToPercentText(parsed.value)}%` : range;
}

function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">{children}</div>
    </section>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{children}</span>
  );
}

function FieldError({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-xs text-red-200">{children}</p>;
}

interface TextFieldProps {
  label: string;
  value: string;
  inputMode: "decimal" | "numeric";
  hint: string;
  suffix?: string;
  error?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

function TextField({
  label,
  value,
  inputMode,
  hint,
  suffix,
  error,
  disabled = false,
  onChange,
}: TextFieldProps) {
  return (
    <label className="block">
      <FieldLabel>{label}</FieldLabel>
      <div
        className={`mt-2 flex items-center rounded-lg border bg-slate-950 focus-within:border-cyan-400 ${
          error ? "border-red-500/60" : "border-slate-700"
        }`}
      >
        <input
          type="text"
          inputMode={inputMode}
          autoComplete="off"
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          onChange={(event) => onChange(event.target.value)}
          className="w-full bg-transparent px-3 py-2 font-mono text-sm text-slate-100 outline-none disabled:opacity-60"
        />
        {suffix && <span className="pr-3 text-xs text-slate-500">{suffix}</span>}
      </div>
      {error ? <FieldError>{error}</FieldError> : <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </label>
  );
}
