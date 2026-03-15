"""Add enriched analysis fields to call_analytics

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_analytics", sa.Column("sentiment", sa.String(), nullable=True))
    op.add_column("call_analytics", sa.Column("sentiment_score", sa.Integer(), nullable=True))
    op.add_column("call_analytics", sa.Column("lead_temperature", sa.String(), nullable=True))
    op.add_column("call_analytics", sa.Column("objections", JSONB(), nullable=True))
    op.add_column("call_analytics", sa.Column("buying_signals", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("call_analytics", "buying_signals")
    op.drop_column("call_analytics", "objections")
    op.drop_column("call_analytics", "lead_temperature")
    op.drop_column("call_analytics", "sentiment_score")
    op.drop_column("call_analytics", "sentiment")
