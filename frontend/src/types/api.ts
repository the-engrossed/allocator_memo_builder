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
