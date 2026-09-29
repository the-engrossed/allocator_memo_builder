import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    column_mapping: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)

    source_rows: Mapped[list["SourceRow"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    return_observations: Mapped[list["ReturnObservation"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class SourceRow(Base):
    __tablename__ = "source_rows"
    __table_args__ = (UniqueConstraint("analysis_id", "row_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="source_rows")


class ReturnObservation(Base):
    __tablename__ = "return_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    net_return: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    return_input_unit: Mapped[str] = mapped_column(String(16), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="return_observations")


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    fund_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    field: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_numbers: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    analysis: Mapped[Analysis] = relationship(back_populates="validation_issues")


class Mandate(Base):
    """Allocator constraints for one analysis. All rates and percentages are basis points."""

    __tablename__ = "mandates"
    __table_args__ = (
        CheckConstraint(
            "target_return_bps BETWEEN 0 AND 10000", name="ck_mandates_target_return_bps"
        ),
        CheckConstraint(
            "max_mgmt_fee_bps BETWEEN 0 AND 10000", name="ck_mandates_max_mgmt_fee_bps"
        ),
        CheckConstraint(
            "max_perf_fee_bps BETWEEN 0 AND 10000", name="ck_mandates_max_perf_fee_bps"
        ),
        CheckConstraint("max_notice_days BETWEEN 0 AND 3650", name="ck_mandates_max_notice_days"),
        CheckConstraint(
            "max_lockup_months BETWEEN 0 AND 120", name="ck_mandates_max_lockup_months"
        ),
        CheckConstraint(
            "strategy_concentration_cap_bps BETWEEN 0 AND 10000",
            name="ck_mandates_strategy_concentration_cap_bps",
        ),
        CheckConstraint("max_candidates BETWEEN 1 AND 20", name="ck_mandates_max_candidates"),
        CheckConstraint(
            "min_liquidity_frequency IN ('monthly', 'quarterly', 'semiannual', 'annual')",
            name="ck_mandates_min_liquidity_frequency",
        ),
        CheckConstraint(
            "max_volatility_bps BETWEEN 0 AND 10000", name="ck_mandates_max_volatility_bps"
        ),
        CheckConstraint(
            "max_drawdown_bps BETWEEN 0 AND 10000", name="ck_mandates_max_drawdown_bps"
        ),
        CheckConstraint(
            "min_track_record_months BETWEEN 0 AND 360",
            name="ck_mandates_min_track_record_months",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), primary_key=True
    )
    target_return_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_mgmt_fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_perf_fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_notice_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_lockup_months: Mapped[int] = mapped_column(Integer, nullable=False)
    min_liquidity_frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    max_volatility_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_drawdown_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    min_track_record_months: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_strategies: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    excluded_strategies: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    strategy_concentration_cap_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
