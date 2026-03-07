"""Add ghl_workflows JSONB and max_call_duration to bot_configs.

Revision ID: 004
Revises: 003
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column(
            "ghl_workflows",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "bot_configs",
        sa.Column("max_call_duration", sa.Integer(), nullable=False, server_default="480"),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "max_call_duration")
    op.drop_column("bot_configs", "ghl_workflows")
