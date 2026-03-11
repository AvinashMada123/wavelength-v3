"""Add llm_thinking_enabled toggle to bot_configs.

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bot_configs",
        sa.Column(
            "llm_thinking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade():
    op.drop_column("bot_configs", "llm_thinking_enabled")
