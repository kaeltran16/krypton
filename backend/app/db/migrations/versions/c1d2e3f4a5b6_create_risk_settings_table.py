"""create risk settings table

Revision ID: c1d2e3f4a5b6
Revises: b7e3a1f2c890
Create Date: 2026-03-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b7e3a1f2c890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_settings",
        sa.Column("id", sa.Integer(), primary_key=True, default=1),
        sa.Column("risk_per_trade", sa.Float(), nullable=False, server_default="0.01"),
        sa.Column("max_position_size_usd", sa.Float(), nullable=True),
        sa.Column("daily_loss_limit_pct", sa.Float(), nullable=False, server_default="0.03"),
        sa.Column("max_concurrent_positions", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_exposure_pct", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("cooldown_after_loss_minutes", sa.Integer(), nullable=True),
        sa.Column("max_risk_per_trade_pct", sa.Float(), nullable=False, server_default="0.02"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_risk_settings_singleton"),
    )
    # Seed default row
    op.execute("INSERT INTO risk_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("risk_settings")
