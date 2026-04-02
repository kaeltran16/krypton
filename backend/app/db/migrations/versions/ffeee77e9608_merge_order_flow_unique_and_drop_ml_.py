"""merge order_flow_unique and drop_ml_blend_weight

Revision ID: ffeee77e9608
Revises: a1f2b3c4d5e6, f2a3b4c5d6e7
Create Date: 2026-04-02 06:25:39.284898

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffeee77e9608'
down_revision: Union[str, Sequence[str], None] = ('a1f2b3c4d5e6', 'f2a3b4c5d6e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
