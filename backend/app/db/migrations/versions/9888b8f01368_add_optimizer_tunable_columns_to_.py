"""add optimizer tunable columns to pipeline settings

Revision ID: 9888b8f01368
Revises: e82435cfcb1c
Create Date: 2026-03-30 19:38:45.474874

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9888b8f01368'
down_revision: Union[str, Sequence[str], None] = 'e82435cfcb1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_settings", sa.Column("atr_optimizer_mode", sa.String(16), nullable=True))
    op.add_column("pipeline_settings", sa.Column("ic_prune_threshold", sa.Float, nullable=True))
    op.add_column("pipeline_settings", sa.Column("ic_reenable_threshold", sa.Float, nullable=True))
    op.add_column("pipeline_settings", sa.Column("ew_ic_lookback_days", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_settings", "ew_ic_lookback_days")
    op.drop_column("pipeline_settings", "ic_reenable_threshold")
    op.drop_column("pipeline_settings", "ic_prune_threshold")
    op.drop_column("pipeline_settings", "atr_optimizer_mode")
