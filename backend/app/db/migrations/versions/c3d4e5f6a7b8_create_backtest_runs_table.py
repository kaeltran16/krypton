"""create backtest runs table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("pairs", JSONB(), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("results", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
