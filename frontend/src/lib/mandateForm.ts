import { LIQUIDITY_FREQUENCIES, type LiquidityFrequency, type MandatePayload } from "../types/api";

/** Form initialization for an analysis with no saved mandate. The API applies no defaults. */
export const MANDATE_DEFAULTS: MandatePayload = {
  target_return_bps: 1000,
  max_mgmt_fee_bps: 200,
  max_perf_fee_bps: 2000,
  max_notice_days: 90,
  max_lockup_months: 12,
  min_liquidity_frequency: "quarterly",
  max_volatility_bps: 1500,
  max_drawdown_bps: 2000,
  min_track_record_months: 36,
  preferred_strategies: ["Macro", "Equity L/S", "Credit"],
  excluded_strategies: [],
  strategy_concentration_cap_bps: 4000,
  max_candidates: 5,
};

/** Mirrors the backend MandateIn bounds (inclusive). */
export const MANDATE_LIMITS = {
  target_return_bps: { min: 0, max: 10_000 },
  max_mgmt_fee_bps: { min: 0, max: 10_000 },
  max_perf_fee_bps: { min: 0, max: 10_000 },
  max_volatility_bps: { min: 0, max: 10_000 },
  max_drawdown_bps: { min: 0, max: 10_000 },
  strategy_concentration_cap_bps: { min: 0, max: 10_000 },
  max_notice_days: { min: 0, max: 3650 },
  max_lockup_months: { min: 0, max: 120 },
  min_track_record_months: { min: 0, max: 360 },
  max_candidates: { min: 1, max: 20 },
} as const;

/** Raw form state. Numeric fields stay as text so no value passes through floating point. */
export interface MandateDraft {
  target_return_pct: string;
  max_mgmt_fee_bps: string;
  max_perf_fee_bps: string;
  max_notice_days: string;
  max_lockup_months: string;
  min_liquidity_frequency: LiquidityFrequency;
  max_volatility_pct: string;
  max_drawdown_pct: string;
  min_track_record_months: string;
  preferred_strategies: string[];
  excluded_strategies: string[];
  strategy_concentration_cap_pct: string;
  max_candidates: string;
}

export type MandateDraftField = keyof MandateDraft;
export type TextDraftField = Exclude<
  MandateDraftField,
  "min_liquidity_frequency" | "preferred_strategies" | "excluded_strategies"
>;
export type MandateFieldErrors = Partial<Record<MandateDraftField, string>>;
export type StrategyRole = "preferred" | "excluded";

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

export function isLiquidityFrequency(value: string): value is LiquidityFrequency {
  return (LIQUIDITY_FREQUENCIES as readonly string[]).includes(value);
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
 * other current selections. Anchoring on the saved lists keeps chip positions stable while
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

/** Toggles a strategy in one role; adding it to a role removes it from the other. */
export function toggleStrategyRole(
  draft: MandateDraft,
  strategy: string,
  role: StrategyRole,
): MandateDraft {
  const preferred = role === "preferred";
  const own = preferred ? draft.preferred_strategies : draft.excluded_strategies;
  const other = preferred ? draft.excluded_strategies : draft.preferred_strategies;
  const nextOwn = toggleStrategy(own, strategy);
  const nextOther = nextOwn.includes(strategy) ? other.filter((name) => name !== strategy) : other;
  return {
    ...draft,
    preferred_strategies: preferred ? nextOwn : nextOther,
    excluded_strategies: preferred ? nextOther : nextOwn,
  };
}

export function draftFromMandate(mandate: MandatePayload): MandateDraft {
  return {
    target_return_pct: bpsToPercentText(mandate.target_return_bps),
    max_mgmt_fee_bps: String(mandate.max_mgmt_fee_bps),
    max_perf_fee_bps: String(mandate.max_perf_fee_bps),
    max_notice_days: String(mandate.max_notice_days),
    max_lockup_months: String(mandate.max_lockup_months),
    min_liquidity_frequency: mandate.min_liquidity_frequency,
    max_volatility_pct: bpsToPercentText(mandate.max_volatility_bps),
    max_drawdown_pct: bpsToPercentText(mandate.max_drawdown_bps),
    min_track_record_months: String(mandate.min_track_record_months),
    preferred_strategies: normalizeStrategies(mandate.preferred_strategies),
    excluded_strategies: normalizeStrategies(mandate.excluded_strategies),
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

  function percent(field: TextDraftField, limit: { min: number; max: number }): number {
    return take(field, parsePercentToBps(draft[field], limit.min, limit.max));
  }

  function integer(field: TextDraftField, limit: { min: number; max: number }): number {
    return take(field, parseInteger(draft[field], limit.min, limit.max));
  }

  if (!isLiquidityFrequency(draft.min_liquidity_frequency)) {
    errors.min_liquidity_frequency = "Choose a redemption frequency.";
  }

  const payload: MandatePayload = {
    target_return_bps: percent("target_return_pct", limits.target_return_bps),
    max_mgmt_fee_bps: integer("max_mgmt_fee_bps", limits.max_mgmt_fee_bps),
    max_perf_fee_bps: integer("max_perf_fee_bps", limits.max_perf_fee_bps),
    max_notice_days: integer("max_notice_days", limits.max_notice_days),
    max_lockup_months: integer("max_lockup_months", limits.max_lockup_months),
    min_liquidity_frequency: draft.min_liquidity_frequency,
    max_volatility_bps: percent("max_volatility_pct", limits.max_volatility_bps),
    max_drawdown_bps: percent("max_drawdown_pct", limits.max_drawdown_bps),
    min_track_record_months: integer("min_track_record_months", limits.min_track_record_months),
    preferred_strategies: normalizeStrategies(draft.preferred_strategies),
    excluded_strategies: normalizeStrategies(draft.excluded_strategies),
    strategy_concentration_cap_bps: percent(
      "strategy_concentration_cap_pct",
      limits.strategy_concentration_cap_bps,
    ),
    max_candidates: integer("max_candidates", limits.max_candidates),
  };

  const overlap = payload.preferred_strategies.filter((name) =>
    payload.excluded_strategies.includes(name),
  );
  if (overlap.length > 0) {
    errors.excluded_strategies = `Cannot be both preferred and excluded: ${overlap.join(", ")}.`;
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, payload };
}

export function draftsEqual(left: MandateDraft, right: MandateDraft): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
