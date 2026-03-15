"""lower signal threshold to 40

Revision ID: 399ffdd585af
Revises: 18b516591cc5
Create Date: 2026-03-15 14:30:14.826316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '399ffdd585af'
down_revision: Union[str, Sequence[str], None] = '18b516591cc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE pipeline_settings SET signal_threshold = 40 WHERE id = 1")


def downgrade() -> None:
    op.execute("UPDATE pipeline_settings SET signal_threshold = 50 WHERE id = 1")
