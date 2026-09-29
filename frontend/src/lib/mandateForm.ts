import type { MandatePayload } from "../types/api";

/** Form initialization for an analysis with no saved mandate. The API applies no defaults. */
export const MANDATE_DEFAULTS: MandatePayload = {
  target_return_bps: 1000,
  max_mgmt_fee_bps: 200,
  max_perf_fee_bps: 2000,
  max_notice_days: 90,
  max_lockup_months: 12,
  preferred_strategies: ["Macro", "Equity L/S", "Credit"],
  strategy_concentration_cap_bps: 4000,
  max_candidates: 5,
};

/** Mirrors the backend MandateIn bounds (inclusive). */
export const MANDATE_LIMITS = {
  target_return_bps: { min: 0, max: 10_000 },
  max_mgmt_fee_bps: { min: 0, max: 10_000 },
  max_perf_fee_bps: { min: 0, max: 10_000 },
  strategy_concentration_cap_bps: { min: 0, max: 10_000 },
  max_notice_days: { min: 0, max: 3650 },
  max_lockup_months: { min: 0, max: 120 },
  max_candidates: { min: 1, max: 20 },
} as const;

/** Raw form state. Numeric fields stay as text so no value passes through floating point. */
export interface MandateDraft {
  target_return_pct: string;
  max_mgmt_fee_bps: string;
  max_perf_fee_bps: string;
  max_notice_days: string;
  max_lockup_months: string;
  preferred_strategies: string[];
  strategy_concentration_cap_pct: string;
  max_candidates: string;
}

export type MandateDraftField = keyof MandateDraft;
export type MandateFieldErrors = Partial<Record<MandateDraftField, string>>;

export type DraftResult =
  | { ok: true; payload: MandatePayload }
  | { ok: false; errors: MandateFieldErrors };

type Parsed = { ok: true; value: number } | { ok: false; error: string };

const PERCENT_PATTERN = /^(\d+)(?:\.(\d{1,2}))?$/;
const OVER_PRECISE_PERCENT_PATTERN = /^\d+\.\d{3,}$/;
const INTEGER_PATTERN = /^\d+$/;

/** Formats integer basis points as a percentage string: 1000 -> "10.00", 29 -> "0.29". */
export function bpsToPercentText(bps: number): string {
  const fraction = bps % 100;
  const whole = (bps - fraction) / 100;
  return `${whole}.${String(fraction).padStart(2, "0")}`;
}

/** Parses a percentage with at most two decimals into exact integer basis points. */
export function parsePercentToBps(text: string, min: number, max: number): Parsed {
  const value = text.trim();
  if (value === "") {
    return { ok: false, error: "Required." };
  }
  if (OVER_PRECISE_PERCENT_PATTERN.test(value)) {
    return { ok: false, error: "Use at most two decimal places (0.01% = 1 bp)." };
  }
  const match = PERCENT_PATTERN.exec(value);
  if (!match) {
    return { ok: false, error: "Enter a non-negative percentage, e.g. 10 or 10.25." };
  }
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(2, "0"));
  return inRange(whole * 100 + fraction, min, max, (bps) => `${bpsToPercentText(bps)}%`);
}

export function parseInteger(text: string, min: number, max: number): Parsed {
  const value = text.trim();
  if (value === "") {
    return { ok: false, error: "Required." };
  }
  if (!INTEGER_PATTERN.test(value)) {
    return { ok: false, error: "Enter a whole number." };
  }
  return inRange(Number(value), min, max, String);
}

function inRange(
  value: number,
  min: number,
  max: number,
  format: (value: number) => string,
): Parsed {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    return { ok: false, error: `Must be between ${format(min)} and ${format(max)}.` };
  }
  return { ok: true, value };
}

/** Trims, drops blanks, and removes duplicates while keeping first-seen order. */
export function normalizeStrategies(strategies: readonly string[]): string[] {
  const normalized: string[] = [];
  for (const strategy of strategies) {
    const name = strategy.trim();
    if (name !== "" && !normalized.includes(name)) {
      normalized.push(name);
    }
  }
  return normalized;
}

/**
 * Ordered union of saved selections, explicit defaults, uploaded-universe strategies, and any
 * other current selections. Anchoring on the saved list keeps chip positions stable while
 * the user toggles.
 */
export function strategyOptions(
  saved: readonly string[],
  universe: readonly string[],
  current: readonly string[],
): string[] {
  return normalizeStrategies([
    ...saved,
    ...MANDATE_DEFAULTS.preferred_strategies,
    ...universe,
    ...current,
  ]);
}

export function toggleStrategy(selected: readonly string[], strategy: string): string[] {
  return selected.includes(strategy)
    ? selected.filter((name) => name !== strategy)
    : [...selected, strategy];
}

export function draftFromMandate(mandate: MandatePayload): MandateDraft {
  return {
    target_return_pct: bpsToPercentText(mandate.target_return_bps),
    max_mgmt_fee_bps: String(mandate.max_mgmt_fee_bps),
    max_perf_fee_bps: String(mandate.max_perf_fee_bps),
    max_notice_days: String(mandate.max_notice_days),
    max_lockup_months: String(mandate.max_lockup_months),
    preferred_strategies: normalizeStrategies(mandate.preferred_strategies),
    strategy_concentration_cap_pct: bpsToPercentText(mandate.strategy_concentration_cap_bps),
    max_candidates: String(mandate.max_candidates),
  };
}

/** Validates the whole draft and builds a complete PUT body, or returns per-field errors. */
export function draftToPayload(draft: MandateDraft): DraftResult {
  const limits = MANDATE_LIMITS;
  const errors: MandateFieldErrors = {};

  function take(field: MandateDraftField, parsed: Parsed): number {
    if (parsed.ok) {
      return parsed.value;
    }
    errors[field] = parsed.error;
    return 0;
  }

  const target = limits.target_return_bps;
  const mgmt = limits.max_mgmt_fee_bps;
  const perf = limits.max_perf_fee_bps;
  const notice = limits.max_notice_days;
  const lockup = limits.max_lockup_months;
  const cap = limits.strategy_concentration_cap_bps;
  const candidates = limits.max_candidates;

  const payload: MandatePayload = {
    target_return_bps: take(
      "target_return_pct",
      parsePercentToBps(draft.target_return_pct, target.min, target.max),
    ),
    max_mgmt_fee_bps: take("max_mgmt_fee_bps", parseInteger(draft.max_mgmt_fee_bps, mgmt.min, mgmt.max)),
    max_perf_fee_bps: take("max_perf_fee_bps", parseInteger(draft.max_perf_fee_bps, perf.min, perf.max)),
    max_notice_days: take(
      "max_notice_days",
      parseInteger(draft.max_notice_days, notice.min, notice.max),
    ),
    max_lockup_months: take(
      "max_lockup_months",
      parseInteger(draft.max_lockup_months, lockup.min, lockup.max),
    ),
    preferred_strategies: normalizeStrategies(draft.preferred_strategies),
    strategy_concentration_cap_bps: take(
      "strategy_concentration_cap_pct",
      parsePercentToBps(draft.strategy_concentration_cap_pct, cap.min, cap.max),
    ),
    max_candidates: take(
      "max_candidates",
      parseInteger(draft.max_candidates, candidates.min, candidates.max),
    ),
  };

  if (payload.preferred_strategies.length === 0) {
    errors.preferred_strategies = "Select at least one strategy.";
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, payload };
}

export function draftsEqual(left: MandateDraft, right: MandateDraft): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
