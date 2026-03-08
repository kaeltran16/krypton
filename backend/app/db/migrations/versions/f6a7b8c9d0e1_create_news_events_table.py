"""create news events table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("impact", sa.String(length=16), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("affected_pairs", JSONB(), nullable=False),
        sa.Column("llm_summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_news_url"),
        sa.UniqueConstraint("fingerprint", name="uq_news_fingerprint"),
    )
    op.create_index("ix_news_impact_published", "news_events", ["impact", "published_at"])


def downgrade() -> None:
    op.drop_index("ix_news_impact_published", table_name="news_events")
    op.drop_table("news_events")
