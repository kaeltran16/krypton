"""add news sentiment weights and correlation dampener

Revision ID: b3a4e7f12d01
Revises: da9705f5c496
Create Date: 2026-03-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3a4e7f12d01'
down_revision: Union[str, Sequence[str], None] = 'da9705f5c496'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # News sentiment outer weights on regime_weights (4 regimes)
    op.add_column("regime_weights", sa.Column("trending_news_weight", sa.Float, nullable=False, server_default="0.06"))
    op.add_column("regime_weights", sa.Column("ranging_news_weight", sa.Float, nullable=False, server_default="0.08"))
    op.add_column("regime_weights", sa.Column("volatile_news_weight", sa.Float, nullable=False, server_default="0.12"))
    op.add_column("regime_weights", sa.Column("steady_news_weight", sa.Float, nullable=False, server_default="0.04"))

    # News score column on pipeline_evaluations
    op.add_column("pipeline_evaluations", sa.Column("news_score", sa.Integer, nullable=True))

    # Correlation dampener floor on pipeline_settings
    op.add_column("pipeline_settings", sa.Column("correlation_dampening_floor", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_settings", "correlation_dampening_floor")
    op.drop_column("pipeline_evaluations", "news_score")
    op.drop_column("regime_weights", "steady_news_weight")
    op.drop_column("regime_weights", "volatile_news_weight")
    op.drop_column("regime_weights", "ranging_news_weight")
    op.drop_column("regime_weights", "trending_news_weight")
