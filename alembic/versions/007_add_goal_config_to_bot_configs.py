"""Add goal_config JSONB column to bot_configs.

Revision ID: 007
Revises: 006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("goal_config", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("bot_configs", "goal_config")
