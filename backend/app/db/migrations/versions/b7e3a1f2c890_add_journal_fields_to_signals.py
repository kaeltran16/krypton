"""add journal fields to signals

Revision ID: b7e3a1f2c890
Revises: 40c06f2d45a2
Create Date: 2026-03-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7e3a1f2c890"
down_revision: Union[str, Sequence[str], None] = "40c06f2d45a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("user_note", sa.String(length=500), nullable=True))
    op.add_column(
        "signals",
        sa.Column(
            "user_status",
            sa.String(length=16),
            nullable=False,
            server_default="OBSERVED",
        ),
    )


def downgrade() -> None:
    op.drop_column("signals", "user_status")
    op.drop_column("signals", "user_note")
