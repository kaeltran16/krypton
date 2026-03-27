"""replace confluence_max_score with multi-level confluence params

Revision ID: c4f5a6b7d8e9
Revises: 8fac78ecf858
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f5a6b7d8e9'
down_revision: Union[str, Sequence[str], None] = '8fac78ecf858'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PipelineSettings: drop confluence_max_score, add 6 confluence params
    op.drop_column('pipeline_settings', 'confluence_max_score')
    op.add_column('pipeline_settings', sa.Column('confluence_level_weight_1', sa.Float(), nullable=True))
    op.add_column('pipeline_settings', sa.Column('confluence_level_weight_2', sa.Float(), nullable=True))
    op.add_column('pipeline_settings', sa.Column('confluence_trend_alignment_steepness', sa.Float(), nullable=True))
    op.add_column('pipeline_settings', sa.Column('confluence_adx_strength_center', sa.Float(), nullable=True))
    op.add_column('pipeline_settings', sa.Column('confluence_adx_conviction_ratio', sa.Float(), nullable=True))
    op.add_column('pipeline_settings', sa.Column('confluence_mr_penalty_factor', sa.Float(), nullable=True))

    # RegimeWeights: add 4 confluence weight columns
    op.add_column('regime_weights', sa.Column('trending_confluence_weight', sa.Float(), nullable=False, server_default='0.14'))
    op.add_column('regime_weights', sa.Column('ranging_confluence_weight', sa.Float(), nullable=False, server_default='0.08'))
    op.add_column('regime_weights', sa.Column('volatile_confluence_weight', sa.Float(), nullable=False, server_default='0.12'))
    op.add_column('regime_weights', sa.Column('steady_confluence_weight', sa.Float(), nullable=False, server_default='0.14'))


def downgrade() -> None:
    op.drop_column('regime_weights', 'steady_confluence_weight')
    op.drop_column('regime_weights', 'volatile_confluence_weight')
    op.drop_column('regime_weights', 'ranging_confluence_weight')
    op.drop_column('regime_weights', 'trending_confluence_weight')

    op.drop_column('pipeline_settings', 'confluence_mr_penalty_factor')
    op.drop_column('pipeline_settings', 'confluence_adx_conviction_ratio')
    op.drop_column('pipeline_settings', 'confluence_adx_strength_center')
    op.drop_column('pipeline_settings', 'confluence_trend_alignment_steepness')
    op.drop_column('pipeline_settings', 'confluence_level_weight_2')
    op.drop_column('pipeline_settings', 'confluence_level_weight_1')
    op.add_column('pipeline_settings', sa.Column('confluence_max_score', sa.Integer(), nullable=True))
