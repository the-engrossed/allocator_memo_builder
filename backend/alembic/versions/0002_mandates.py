"""Mandate configuration, one-to-one with an analysis.

Revision ID: 0002_mandates
Revises: 0001_ingestion
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_mandates"
down_revision: Union[str, None] = "0001_ingestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_return_bps", sa.Integer(), nullable=False),
        sa.Column("max_mgmt_fee_bps", sa.Integer(), nullable=False),
        sa.Column("max_perf_fee_bps", sa.Integer(), nullable=False),
        sa.Column("max_notice_days", sa.Integer(), nullable=False),
        sa.Column("max_lockup_months", sa.Integer(), nullable=False),
        sa.Column("preferred_strategies", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("strategy_concentration_cap_bps", sa.Integer(), nullable=False),
        sa.Column("max_candidates", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("analysis_id"),
        sa.CheckConstraint(
            "target_return_bps BETWEEN 0 AND 10000", name="ck_mandates_target_return_bps"
        ),
        sa.CheckConstraint(
            "max_mgmt_fee_bps BETWEEN 0 AND 10000", name="ck_mandates_max_mgmt_fee_bps"
        ),
        sa.CheckConstraint(
            "max_perf_fee_bps BETWEEN 0 AND 10000", name="ck_mandates_max_perf_fee_bps"
        ),
        sa.CheckConstraint(
            "max_notice_days BETWEEN 0 AND 3650", name="ck_mandates_max_notice_days"
        ),
        sa.CheckConstraint(
            "max_lockup_months BETWEEN 0 AND 120", name="ck_mandates_max_lockup_months"
        ),
        sa.CheckConstraint(
            "strategy_concentration_cap_bps BETWEEN 0 AND 10000",
            name="ck_mandates_strategy_concentration_cap_bps",
        ),
        sa.CheckConstraint(
            "max_candidates BETWEEN 1 AND 20", name="ck_mandates_max_candidates"
        ),
        sa.CheckConstraint(
            "cardinality(preferred_strategies) > 0", name="ck_mandates_preferred_strategies"
        ),
    )


def downgrade() -> None:
    op.drop_table("mandates")
