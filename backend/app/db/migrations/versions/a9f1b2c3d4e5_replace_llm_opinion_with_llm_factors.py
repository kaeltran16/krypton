"""replace llm_opinion and llm_confidence with llm_factors

Revision ID: a9f1b2c3d4e5
Revises: d8d18eff4af0
Create Date: 2026-03-18 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9f1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'd8d18eff4af0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # add new llm_factors JSONB column
    op.add_column('signals', sa.Column('llm_factors', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # preserve historical LLM opinion/confidence in raw_indicators before dropping columns
    op.execute("""
        UPDATE signals
        SET raw_indicators = COALESCE(raw_indicators, '{}'::jsonb)
            || jsonb_build_object(
                'legacy_llm_opinion', llm_opinion,
                'legacy_llm_confidence', llm_confidence
            )
        WHERE llm_opinion IS NOT NULL OR llm_confidence IS NOT NULL
    """)

    # drop old columns
    op.drop_column('signals', 'llm_opinion')
    op.drop_column('signals', 'llm_confidence')


def downgrade() -> None:
    op.add_column('signals', sa.Column('llm_confidence', sa.String(length=8), nullable=True))
    op.add_column('signals', sa.Column('llm_opinion', sa.String(length=16), nullable=True))
    op.drop_column('signals', 'llm_factors')
