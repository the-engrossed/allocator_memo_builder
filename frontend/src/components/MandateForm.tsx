import type { FormEvent, ReactNode } from "react";
import {
  MANDATE_LIMITS,
  bpsToPercentText,
  isLiquidityFrequency,
  parseInteger,
  type MandateDraft,
  type MandateFieldErrors,
  type StrategyRole,
  type TextDraftField,
} from "../lib/mandateForm";
import { LIQUIDITY_FREQUENCIES, type LiquidityFrequency } from "../types/api";
import { StrategyChips } from "./StrategyChips";

export type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; updatedAt: string }
  | { status: "error"; message: string };

const LIQUIDITY_LABELS: Record<LiquidityFrequency, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly or more often",
  semiannual: "Semiannual or more often",
  annual: "Annual or more often",
};

interface MandateFormProps {
  draft: MandateDraft;
  errors: MandateFieldErrors;
  strategyOptions: string[];
  universeStrategies: string[];
  saveState: SaveState;
  statusNote: ReactNode;
  onChange: (field: TextDraftField, value: string) => void;
  onLiquidityChange: (value: LiquidityFrequency) => void;
  onToggleStrategy: (strategy: string, role: StrategyRole) => void;
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
  onLiquidityChange,
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
      <FormSection
        title="Hard screens · Liquidity & fees"
        description="A fund must pass every hard screen to be ranked. Boundaries are inclusive."
      >
        <label className="block">
          <FieldLabel>Min redemption frequency</FieldLabel>
          <select
            value={draft.min_liquidity_frequency}
            disabled={saving}
            onChange={(event) => {
              if (isLiquidityFrequency(event.target.value)) {
                onLiquidityChange(event.target.value);
              }
            }}
            className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400 disabled:opacity-60"
          >
            {LIQUIDITY_FREQUENCIES.map((frequency) => (
              <option key={frequency} value={frequency}>
                {LIQUIDITY_LABELS[frequency]}
              </option>
            ))}
          </select>
          {errors.min_liquidity_frequency ? (
            <FieldError>{errors.min_liquidity_frequency}</FieldError>
          ) : (
            <p className="mt-1 text-xs text-slate-500">Funds must redeem at least this often.</p>
          )}
        </label>
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

      <FormSection title="Hard screens · Risk & track record">
        <TextField
          label="Max annualized volatility"
          suffix="%"
          inputMode="decimal"
          value={draft.max_volatility_pct}
          error={errors.max_volatility_pct}
          disabled={saving}
          hint="0–100%. Up to two decimals."
          onChange={(value) => onChange("max_volatility_pct", value)}
        />
        <TextField
          label="Max drawdown"
          suffix="%"
          inputMode="decimal"
          value={draft.max_drawdown_pct}
          error={errors.max_drawdown_pct}
          disabled={saving}
          hint="Peak-to-trough loss tolerance, 0–100%. Up to two decimals."
          onChange={(value) => onChange("max_drawdown_pct", value)}
        />
        <TextField
          label="Min track record"
          suffix="months"
          inputMode="numeric"
          value={draft.min_track_record_months}
          error={errors.min_track_record_months}
          disabled={saving}
          hint="Months of valid return history, 0–360."
          onChange={(value) => onChange("min_track_record_months", value)}
        />
        <div className="sm:col-span-3">
          <FieldLabel>Excluded strategies</FieldLabel>
          <div className="mt-2">
            <StrategyChips
              tone="exclude"
              options={strategyOptions}
              selected={draft.excluded_strategies}
              universe={universeStrategies}
              disabled={saving}
              onToggle={(strategy) => onToggleStrategy(strategy, "excluded")}
            />
          </div>
          {errors.excluded_strategies ? (
            <FieldError>{errors.excluded_strategies}</FieldError>
          ) : (
            <p className="mt-1 text-xs text-slate-500">
              Funds in these strategies are ineligible. Optional.
            </p>
          )}
        </div>
      </FormSection>

      <FormSection
        title="Shortlist construction"
        description="Applied to the ranked eligible funds. These never change eligibility or a fund's score."
      >
        <div className="sm:col-span-3">
          <FieldLabel>Preferred strategies</FieldLabel>
          <div className="mt-2">
            <StrategyChips
              tone="prefer"
              options={strategyOptions}
              selected={draft.preferred_strategies}
              universe={universeStrategies}
              disabled={saving}
              onToggle={(strategy) => onToggleStrategy(strategy, "preferred")}
            />
          </div>
          {errors.preferred_strategies ? (
            <FieldError>{errors.preferred_strategies}</FieldError>
          ) : (
            <p className="mt-1 text-xs text-slate-500">
              A preference, not a whitelist: preferred strategies fill the shortlist first, then
              other eligible funds in rank order. Optional.
            </p>
          )}
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
        <TextField
          label="Max candidates"
          inputMode="numeric"
          value={draft.max_candidates}
          error={errors.max_candidates}
          disabled={saving}
          hint="Whole number, 1–20."
          onChange={(value) => onChange("max_candidates", value)}
        />
        <TextField
          label="Target return"
          suffix="%"
          inputMode="decimal"
          value={draft.target_return_pct}
          error={errors.target_return_pct}
          disabled={saving}
          hint="Reporting reference only; never excludes or reorders a fund. 0.01% = 1 bp."
          onChange={(value) => onChange("target_return_pct", value)}
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

function FormSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      {description && <p className="mt-1 text-xs text-slate-400">{description}</p>}
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
