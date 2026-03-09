"""Add llm_provider and llm_model columns to bot_configs.

Revision ID: 011
Revises: 010
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("llm_provider", sa.Text(), nullable=False, server_default="google"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("llm_model", sa.Text(), nullable=False, server_default="gemini-2.5-flash"),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "llm_model")
    op.drop_column("bot_configs", "llm_provider")
