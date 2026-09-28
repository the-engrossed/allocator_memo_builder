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

export interface HealthResponse {
  status: string;
  db: boolean;
  openai_configured: boolean;
  fred_configured: boolean;
}
