"""Record how many OpenAI calls each memo made.

Existing memos keep NULL (attempt count unknown); new memos always record 0, 1, or 2.

Revision ID: 0006_memo_llm_attempts
Revises: 0005_memo_artifacts
Create Date: 2026-09-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_memo_llm_attempts"
down_revision: Union[str, None] = "0005_memo_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memo_artifacts", sa.Column("llm_attempts", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_memo_artifacts_llm_attempts",
        "memo_artifacts",
        "llm_attempts IS NULL OR llm_attempts BETWEEN 0 AND 2",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memo_artifacts_llm_attempts", "memo_artifacts", type_="check")
    op.drop_column("memo_artifacts", "llm_attempts")
