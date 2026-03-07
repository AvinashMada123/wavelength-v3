"""Add GHL API key, location ID, and post-call tag to bot_configs.

Revision ID: 003
Revises: 002
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("ghl_api_key", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("ghl_location_id", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("ghl_post_call_tag", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_configs", "ghl_post_call_tag")
    op.drop_column("bot_configs", "ghl_location_id")
    op.drop_column("bot_configs", "ghl_api_key")
