"""reduce llm factor total cap to 25

Revision ID: e82435cfcb1c
Revises: 3fb959be4e78
Create Date: 2026-03-30 19:22:22.257482

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e82435cfcb1c'
down_revision: Union[str, Sequence[str], None] = '3fb959be4e78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE pipeline_settings "
        "SET llm_factor_total_cap = 25.0 "
        "WHERE llm_factor_total_cap = 35.0 OR llm_factor_total_cap IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pipeline_settings "
        "SET llm_factor_total_cap = 35.0 "
        "WHERE llm_factor_total_cap = 25.0"
    )
