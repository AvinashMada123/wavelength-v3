"""add webhook_url and webhook_headers to sequence_steps

Revision ID: 035
Revises: 034
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sequence_steps",
        sa.Column("webhook_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "sequence_steps",
        sa.Column("webhook_headers", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sequence_steps", "webhook_headers")
    op.drop_column("sequence_steps", "webhook_url")
