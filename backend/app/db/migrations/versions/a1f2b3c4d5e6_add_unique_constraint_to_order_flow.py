"""add unique constraint to order_flow_snapshots

Revision ID: a1f2b3c4d5e6
Revises: 5fc72700a4c1
Create Date: 2026-04-02 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1f2b3c4d5e6'
down_revision: Union[str, None] = '5fc72700a4c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove duplicate rows, keeping the one with the highest id per (pair, timestamp)
    op.execute(
        """
        DELETE FROM order_flow_snapshots a
        USING order_flow_snapshots b
        WHERE a.pair = b.pair AND a.timestamp = b.timestamp AND a.id < b.id
        """
    )
    op.create_unique_constraint("uq_oflow_pair_ts", "order_flow_snapshots", ["pair", "timestamp"])


def downgrade() -> None:
    op.drop_constraint("uq_oflow_pair_ts", "order_flow_snapshots", type_="unique")
