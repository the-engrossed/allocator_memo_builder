"""Immutable ranking runs and per-fund evaluations.

Revision ID: 0004_ranking_runs
Revises: 0003_mandate_screens
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_ranking_runs"
down_revision: Union[str, None] = "0003_mandate_screens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ranking_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mandate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mandate_sha256", sa.String(length=64), nullable=False),
        sa.Column("benchmark_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ranking_runs_analysis_created", "ranking_runs", ["analysis_id", "created_at"]
    )
    op.create_table(
        "fund_evaluations",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fund_id", sa.Text(), nullable=False),
        sa.Column("fund_name", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("benchmark", sa.String(length=8), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("total_score", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("selection_reason", sa.String(length=32), nullable=True),
        sa.Column("selection_detail", sa.Text(), nullable=True),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("screens", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score_components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["ranking_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "fund_id"),
        sa.CheckConstraint(
            "selection_reason IS NULL OR selection_reason IN ("
            "'SELECTED_PREFERENCE_PASS', 'SELECTED_RANK_PASS', "
            "'CONCENTRATION_SKIP', 'CAPACITY_REACHED')",
            name="ck_fund_evaluations_selection_reason",
        ),
        sa.CheckConstraint(
            "eligible = (rank IS NOT NULL)", name="ck_fund_evaluations_rank_iff_eligible"
        ),
    )


def downgrade() -> None:
    op.drop_table("fund_evaluations")
    op.drop_index("ix_ranking_runs_analysis_created", table_name="ranking_runs")
    op.drop_table("ranking_runs")
