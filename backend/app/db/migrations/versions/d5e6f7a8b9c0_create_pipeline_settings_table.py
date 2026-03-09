"""create pipeline settings table

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-03-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_settings",
        sa.Column("id", sa.Integer(), primary_key=True, default=1),
        sa.Column(
            "pairs",
            JSONB(),
            nullable=False,
            server_default='["BTC-USDT-SWAP", "ETH-USDT-SWAP"]',
        ),
        sa.Column(
            "timeframes",
            JSONB(),
            nullable=False,
            server_default='["15m", "1h", "4h"]',
        ),
        sa.Column(
            "signal_threshold",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
        sa.Column(
            "onchain_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "news_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "news_context_window",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_pipeline_settings_singleton"),
    )
    # Seed default row
    op.execute("INSERT INTO pipeline_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("pipeline_settings")
