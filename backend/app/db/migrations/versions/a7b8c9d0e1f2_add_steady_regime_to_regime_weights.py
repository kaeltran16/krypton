"""add steady regime to regime_weights

Revision ID: a7b8c9d0e1f2
Revises: d571646cd0a9
Create Date: 2026-03-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'd571646cd0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Inner caps for steady regime
    op.add_column('regime_weights', sa.Column('steady_trend_cap', sa.Float(), nullable=False, server_default='40.0'))
    op.add_column('regime_weights', sa.Column('steady_mean_rev_cap', sa.Float(), nullable=False, server_default='15.0'))
    op.add_column('regime_weights', sa.Column('steady_squeeze_cap', sa.Float(), nullable=False, server_default='20.0'))
    op.add_column('regime_weights', sa.Column('steady_volume_cap', sa.Float(), nullable=False, server_default='25.0'))
    # Outer weights for steady regime
    op.add_column('regime_weights', sa.Column('steady_tech_weight', sa.Float(), nullable=False, server_default='0.48'))
    op.add_column('regime_weights', sa.Column('steady_flow_weight', sa.Float(), nullable=False, server_default='0.22'))
    op.add_column('regime_weights', sa.Column('steady_onchain_weight', sa.Float(), nullable=False, server_default='0.18'))
    op.add_column('regime_weights', sa.Column('steady_pattern_weight', sa.Float(), nullable=False, server_default='0.12'))


def downgrade() -> None:
    op.drop_column('regime_weights', 'steady_pattern_weight')
    op.drop_column('regime_weights', 'steady_onchain_weight')
    op.drop_column('regime_weights', 'steady_flow_weight')
    op.drop_column('regime_weights', 'steady_tech_weight')
    op.drop_column('regime_weights', 'steady_volume_cap')
    op.drop_column('regime_weights', 'steady_squeeze_cap')
    op.drop_column('regime_weights', 'steady_mean_rev_cap')
    op.drop_column('regime_weights', 'steady_trend_cap')
