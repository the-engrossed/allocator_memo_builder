export type AnalysisStatus = "invalid" | "needs_review" | "valid_with_warnings" | "valid";
export type IssueSeverity = "error" | "warning" | "info";

export interface ValidationIssue {
  code: string;
  severity: IssueSeverity;
  fund_id: string | null;
  field: string | null;
  row_numbers: number[];
  message: string;
  details: Record<string, unknown>;
}

export interface FundSummary {
  fund_id: string;
  fund_name: string;
  strategy: string;
  liquidity_frequency: string;
  first_period: string | null;
  last_period: string | null;
  observations: number;
  analysis_blocked: boolean;
  issue_counts: {
    error: number;
    warning: number;
    info: number;
  };
}

export interface AnalysisResponse {
  analysis_id: string;
  filename: string;
  status: AnalysisStatus;
  uploaded_at: string;
  row_count: number;
  fund_count: number;
  column_mapping: Record<string, string>;
  strategies: string[];
  issues: ValidationIssue[];
  funds: FundSummary[];
  /** True overlap across funds with ≥12 observations; null when no fund qualifies. */
  common_window?: CommonWindow | null;
}

export interface CommonWindow {
  start: string | null;
  end: string | null;
  months: number;
  fund_count: number;
}

// --- Ranking runs (Phase 3). The backend owns every value; the UI only formats. ---

export type SeriesState = "live" | "cached" | "fallback" | "unavailable";
export type ScreenOutcome = "pass" | "fail" | "unverifiable";
export type SelectionReason =
  | "SELECTED_PREFERENCE_PASS"
  | "SELECTED_RANK_PASS"
  | "CONCENTRATION_SKIP"
  | "CAPACITY_REACHED";

export interface SeriesProvenance {
  provider: string;
  series_id: string;
  state: SeriesState;
  retrieved_at: string | null;
  coverage_start: string | null;
  coverage_end: string | null;
  message: string;
  fallback_annual_bps?: number;
}

export interface ScreenResult {
  code: string;
  screen: string;
  result: ScreenOutcome;
  observed: unknown;
  threshold: unknown;
  reason: string;
}

export interface ScoreComponent {
  value: number | null;
  percentile: number;
  weight: number;
  points: number;
  flag: string | null;
}

export interface FundInput {
  raw: string;
  value: unknown;
  status: string;
  source_row: number;
  evidence_id: string;
}

export interface DataQualityEntry {
  code: string;
  severity: IssueSeverity;
  field: string | null;
  message: string;
  row_numbers: number[];
  evidence_id: string;
}

export interface FundMetrics {
  months_of_history: number | null;
  window_start: string | null;
  window_end: string | null;
  annualized_return_bps: number | null;
  volatility_bps: number | null;
  max_drawdown_bps: number | null;
  sharpe: number | null;
  correlation: number | null;
  correlation_overlap_months: number;
  benchmark: string;
  benchmark_available: boolean | null;
  risk_free_annual_bps: number | null;
  risk_free_source: string | null;
  target_gap_bps: number | null;
  excess_return_bps: number | null;
  /** Older runs predate these maps; treat a missing map as empty. */
  unverifiable_reasons?: Record<string, string>;
  metric_evidence?: Record<string, string>;
}

export interface FundEvaluation {
  fund_id: string;
  fund_name: string;
  strategy: string;
  benchmark: string;
  eligible: boolean;
  rank: number | null;
  total_score: number | null;
  selection_reason: SelectionReason | null;
  selection_detail: string | null;
  inputs: Record<string, FundInput>;
  metrics: FundMetrics | null;
  screens: ScreenResult[];
  score_components: Record<string, ScoreComponent> | null;
  data_quality: DataQualityEntry[];
  evidence_ids: string[];
}

export interface RunWarning {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface RankingRunResponse {
  run_id: string;
  analysis_id: string;
  created_at: string;
  policy_version: string;
  mandate_sha256: string;
  mandate_snapshot: Record<string, unknown>;
  benchmark_provenance: Record<string, SeriesProvenance>;
  score_weights: Record<string, number>;
  warnings: RunWarning[];
  summary: { evaluated: number; eligible: number; excluded: number; shortlisted: number };
  funds: FundEvaluation[];
}

/** Ordered from most to least frequent redemption. */
export const LIQUIDITY_FREQUENCIES = ["monthly", "quarterly", "semiannual", "annual"] as const;
export type LiquidityFrequency = (typeof LIQUIDITY_FREQUENCIES)[number];

/** Full-replacement mandate body. Rates and percentages are integer basis points. */
export interface MandatePayload {
  target_return_bps: number;
  max_mgmt_fee_bps: number;
  max_perf_fee_bps: number;
  max_notice_days: number;
  max_lockup_months: number;
  min_liquidity_frequency: LiquidityFrequency;
  max_volatility_bps: number;
  max_drawdown_bps: number;
  min_track_record_months: number;
  preferred_strategies: string[];
  excluded_strategies: string[];
  strategy_concentration_cap_bps: number;
  max_candidates: number;
}

export interface MandateResponse extends MandatePayload {
  analysis_id: string;
  created_at: string;
  updated_at: string;
}

export interface HealthResponse {
  status: string;
  db: boolean;
  openai_configured: boolean;
  fred_configured: boolean;
}
