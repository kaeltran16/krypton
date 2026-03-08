"""add outcome fields to signals

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-08 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column(
            "outcome",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "signals",
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "signals",
        sa.Column("outcome_pnl_pct", sa.Numeric(precision=10, scale=4), nullable=True),
    )
    op.add_column(
        "signals",
        sa.Column("outcome_duration_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("signals", "outcome_duration_minutes")
    op.drop_column("signals", "outcome_pnl_pct")
    op.drop_column("signals", "outcome_at")
    op.drop_column("signals", "outcome")
