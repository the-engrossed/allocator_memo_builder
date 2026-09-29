from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.domain.enums import (
    AnalysisStatus,
    IssueSeverity,
    LiquidityFrequency,
    ScreenOutcome,
    SelectionReason,
)


class ValidationIssueOut(BaseModel):
    code: str
    severity: IssueSeverity
    fund_id: str | None
    field: str | None
    row_numbers: list[int]
    message: str
    details: dict


class FundSummaryOut(BaseModel):
    fund_id: str
    fund_name: str
    strategy: str
    liquidity_frequency: str
    first_period: date | None
    last_period: date | None
    observations: int
    analysis_blocked: bool
    issue_counts: dict[str, int]


class AnalysisResponse(BaseModel):
    analysis_id: UUID
    filename: str
    status: AnalysisStatus
    uploaded_at: datetime
    row_count: int
    fund_count: int
    column_mapping: dict[str, str]
    strategies: list[str]
    issues: list[ValidationIssueOut]
    funds: list[FundSummaryOut]


BasisPoints = Annotated[StrictInt, Field(ge=0, le=10_000)]


class MandateFields(BaseModel):
    target_return_bps: BasisPoints
    max_mgmt_fee_bps: BasisPoints
    max_perf_fee_bps: BasisPoints
    max_notice_days: Annotated[StrictInt, Field(ge=0, le=3650)]
    max_lockup_months: Annotated[StrictInt, Field(ge=0, le=120)]
    min_liquidity_frequency: LiquidityFrequency
    max_volatility_bps: BasisPoints
    max_drawdown_bps: BasisPoints
    min_track_record_months: Annotated[StrictInt, Field(ge=0, le=360)]
    preferred_strategies: list[StrictStr]
    excluded_strategies: list[StrictStr]
    strategy_concentration_cap_bps: BasisPoints
    max_candidates: Annotated[StrictInt, Field(ge=1, le=20)]


class MandateIn(MandateFields):
    """Full-replacement mandate payload. Every field is required; there are no server defaults."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("preferred_strategies", "excluded_strategies")
    @classmethod
    def _normalize_strategies(cls, strategies: list[str]) -> list[str]:
        normalized: list[str] = []
        for strategy in strategies:
            name = strategy.strip()
            if not name:
                raise ValueError("Strategy names must not be empty.")
            if name not in normalized:
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def _strategies_do_not_overlap(self) -> "MandateIn":
        overlap = [name for name in self.preferred_strategies if name in self.excluded_strategies]
        if overlap:
            raise ValueError(
                "A strategy cannot be both preferred and excluded: " + ", ".join(overlap) + "."
            )
        return self


class MandateResponse(MandateFields):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: UUID
    created_at: datetime
    updated_at: datetime


class ScreenResultOut(BaseModel):
    code: str
    screen: str
    result: ScreenOutcome
    observed: object
    threshold: object
    reason: str


class RunWarningOut(BaseModel):
    code: str
    message: str
    details: dict


class FundEvaluationOut(BaseModel):
    fund_id: str
    fund_name: str
    strategy: str
    benchmark: str
    eligible: bool
    rank: int | None
    total_score: float | None
    selection_reason: SelectionReason | None
    selection_detail: str | None
    inputs: dict
    metrics: dict | None
    screens: list[ScreenResultOut]
    score_components: dict | None
    data_quality: list[dict]
    evidence_ids: list[str]


class RankingRunSummary(BaseModel):
    evaluated: int
    eligible: int
    excluded: int
    shortlisted: int


class RankingRunResponse(BaseModel):
    run_id: UUID
    analysis_id: UUID
    created_at: datetime
    policy_version: str
    mandate_sha256: str
    mandate_snapshot: dict
    benchmark_provenance: dict
    score_weights: dict[str, int]
    warnings: list[RunWarningOut]
    summary: RankingRunSummary
    funds: list[FundEvaluationOut]


class HealthResponse(BaseModel):
    status: str
    db: bool = Field(description="True when the API can query PostgreSQL")
    openai_configured: bool
    fred_configured: bool
