from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import AnalysisStatus, IssueSeverity


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


class HealthResponse(BaseModel):
    status: str
    db: bool = Field(description="True when the API can query PostgreSQL")
    openai_configured: bool
    fred_configured: bool
