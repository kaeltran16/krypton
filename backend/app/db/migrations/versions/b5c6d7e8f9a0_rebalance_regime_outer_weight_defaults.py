"""rebalance regime outer weight defaults for 6-source confluence

Revision ID: b5c6d7e8f9a0
Revises: 446a8d71ae31
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, Sequence[str], None] = '446a8d71ae31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("regime_weights", "steady_tech_weight", server_default="0.36")
    op.alter_column("regime_weights", "steady_flow_weight", server_default="0.16")
    op.alter_column("regime_weights", "steady_onchain_weight", server_default="0.16")
    op.alter_column("regime_weights", "steady_pattern_weight", server_default="0.10")
    op.alter_column("regime_weights", "trending_liquidation_weight", server_default="0.07")
    op.alter_column("regime_weights", "ranging_liquidation_weight", server_default="0.10")
    op.alter_column("regime_weights", "volatile_liquidation_weight", server_default="0.10")


def downgrade() -> None:
    op.alter_column("regime_weights", "steady_tech_weight", server_default="0.48")
    op.alter_column("regime_weights", "steady_flow_weight", server_default="0.22")
    op.alter_column("regime_weights", "steady_onchain_weight", server_default="0.18")
    op.alter_column("regime_weights", "steady_pattern_weight", server_default="0.12")
    op.alter_column("regime_weights", "trending_liquidation_weight", server_default="0.08")
    op.alter_column("regime_weights", "ranging_liquidation_weight", server_default="0.09")
    op.alter_column("regime_weights", "volatile_liquidation_weight", server_default="0.11")
