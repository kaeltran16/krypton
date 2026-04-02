"""drop dead ml_blend_weight column from pipeline_settings

Revision ID: f2a3b4c5d6e7
Revises: 5fc72700a4c1
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = '5fc72700a4c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('pipeline_settings', 'ml_blend_weight')


def downgrade() -> None:
    op.add_column('pipeline_settings', sa.Column('ml_blend_weight', sa.Float(), nullable=True))
