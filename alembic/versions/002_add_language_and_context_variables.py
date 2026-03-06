"""Add language, context_variables, and tts_style_prompt to bot_configs.

Revision ID: 002
Revises: 001
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("language", sa.Text(), nullable=False, server_default="en-IN"),
    )
    op.add_column(
        "bot_configs",
        sa.Column(
            "context_variables",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "context_variables")
    op.drop_column("bot_configs", "language")
