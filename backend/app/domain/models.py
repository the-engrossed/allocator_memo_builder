import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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
