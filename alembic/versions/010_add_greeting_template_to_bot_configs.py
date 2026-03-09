"""Add greeting_template column to bot_configs.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("greeting_template", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "greeting_template")
