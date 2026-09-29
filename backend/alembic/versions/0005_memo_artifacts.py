"""Immutable memo revisions with guard results, appendix, and an evidence snapshot.

Revision ID: 0005_memo_artifacts
Revises: 0004_ranking_runs
Create Date: 2026-09-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_memo_artifacts"
down_revision: Union[str, None] = "0004_ranking_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "memo_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ranking_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("generation_mode", sa.String(length=16), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("claims", _jsonb(), nullable=False),
        sa.Column("guard_results", _jsonb(), nullable=False),
        sa.Column("guard_summary", _jsonb(), nullable=False),
        sa.Column("appendix", _jsonb(), nullable=False),
        sa.Column("evidence_snapshot", _jsonb(), nullable=False),
        sa.Column("token_usage", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ranking_run_id"], ["ranking_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ranking_run_id", "revision", name="uq_memo_artifacts_run_revision"),
        sa.CheckConstraint(
            "generation_mode IN ('llm', 'template')", name="ck_memo_artifacts_generation_mode"
        ),
    )


def downgrade() -> None:
    op.drop_table("memo_artifacts")
