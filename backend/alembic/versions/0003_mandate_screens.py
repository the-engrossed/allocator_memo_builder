"""Mandate hard-screen fields; preferred strategies may be empty.

Existing mandates are backfilled with values that screen nothing (annual liquidity, 10000 bps
volatility and drawdown caps, no track-record minimum, no exclusions) so the migration does not
invent constraints the allocator never set. The server defaults are dropped afterwards because
the API requires every field on every PUT.

Downgrade fails if any mandate has an empty preferred_strategies list.

Revision ID: 0003_mandate_screens
Revises: 0002_mandates
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_mandate_screens"
down_revision: Union[str, None] = "0002_mandates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKFILL: dict[str, tuple[sa.types.TypeEngine, sa.TextClause]] = {
    "min_liquidity_frequency": (sa.String(length=16), sa.text("'annual'")),
    "max_volatility_bps": (sa.Integer(), sa.text("10000")),
    "max_drawdown_bps": (sa.Integer(), sa.text("10000")),
    "min_track_record_months": (sa.Integer(), sa.text("0")),
    "excluded_strategies": (postgresql.ARRAY(sa.Text()), sa.text("'{}'::text[]")),
}

_CHECKS: dict[str, str] = {
    "ck_mandates_min_liquidity_frequency": (
        "min_liquidity_frequency IN ('monthly', 'quarterly', 'semiannual', 'annual')"
    ),
    "ck_mandates_max_volatility_bps": "max_volatility_bps BETWEEN 0 AND 10000",
    "ck_mandates_max_drawdown_bps": "max_drawdown_bps BETWEEN 0 AND 10000",
    "ck_mandates_min_track_record_months": "min_track_record_months BETWEEN 0 AND 360",
}


def upgrade() -> None:
    for name, (column_type, backfill) in _BACKFILL.items():
        op.add_column(
            "mandates", sa.Column(name, column_type, nullable=False, server_default=backfill)
        )
        op.alter_column("mandates", name, server_default=None)
    for name, condition in _CHECKS.items():
        op.create_check_constraint(name, "mandates", condition)
    op.drop_constraint("ck_mandates_preferred_strategies", "mandates", type_="check")


def downgrade() -> None:
    op.create_check_constraint(
        "ck_mandates_preferred_strategies", "mandates", "cardinality(preferred_strategies) > 0"
    )
    for name in _CHECKS:
        op.drop_constraint(name, "mandates", type_="check")
    for name in _BACKFILL:
        op.drop_column("mandates", name)
