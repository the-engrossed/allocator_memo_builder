"""Store the LLM-proposed ranking and its comparison to the deterministic baseline.

Memos created before memo-v3 keep NULL.

Revision ID: 0007_memo_llm_ranking
Revises: 0006_memo_llm_attempts
Create Date: 2026-09-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007_memo_llm_ranking"
down_revision: Union[str, None] = "0006_memo_llm_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memo_artifacts", sa.Column("llm_ranking", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memo_artifacts", "llm_ranking")
