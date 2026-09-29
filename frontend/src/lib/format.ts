/** Display formatting only. No screening, scoring, ranking, or metric logic belongs here. */
import type { SelectionReason, SeriesState } from "../types/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Integer basis points as a percentage with two decimals, e.g. 1268 -> "12.68%". */
export function formatBps(bps: number, { signed = false } = {}): string {
  const sign = bps < 0 ? "−" : signed && bps > 0 ? "+" : "";
  const magnitude = Math.abs(bps);
  const fraction = magnitude % 100;
  const whole = (magnitude - fraction) / 100;
  return `${sign}${whole}.${String(fraction).padStart(2, "0")}%`;
}

/** Backend ratios are already rounded to 2 dp; this only fixes the display width. */
export function formatRatio(value: number): string {
  return value < 0 ? `−${Math.abs(value).toFixed(2)}` : value.toFixed(2);
}

/** "2021-09-01" -> "Sep 2021", parsed as text so no time zone can shift the month. */
export function formatMonth(isoDate: string | null | undefined): string {
  if (!isoDate) {
    return "—";
  }
  const [year, month] = isoDate.split("-");
  const index = Number(month) - 1;
  return MONTHS[index] ? `${MONTHS[index]} ${year}` : isoDate;
}

export function formatMonthRange(start: string | null | undefined, end: string | null | undefined): string {
  return `${formatMonth(start)} → ${formatMonth(end)}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

export function shortHash(hash: string, length = 12): string {
  return hash.length > length ? `${hash.slice(0, length)}…` : hash;
}

export function formatObserved(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "none";
  }
  return String(value);
}

export const SELECTION_LABELS: Record<SelectionReason, string> = {
  SELECTED_PREFERENCE_PASS: "Selected · preferred strategy",
  SELECTED_RANK_PASS: "Selected · rank order",
  CONCENTRATION_SKIP: "Skipped · strategy concentration cap",
  CAPACITY_REACHED: "Not selected · shortlist full",
};

export const STATE_LABELS: Record<SeriesState, string> = {
  live: "Live",
  cached: "Cached",
  fallback: "Fallback",
  unavailable: "Unavailable",
};

export const COMPONENT_LABELS: Record<string, string> = {
  sharpe: "Sharpe",
  annualized_return: "Return",
  drawdown_resilience: "Drawdown",
  low_correlation: "Low corr.",
};

export const COMPONENT_ORDER = ["sharpe", "annualized_return", "drawdown_resilience", "low_correlation"];
