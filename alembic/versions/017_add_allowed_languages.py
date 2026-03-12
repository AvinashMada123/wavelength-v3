"""Add allowed_languages to bot_configs for constraining switch_language.

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bot_configs",
        sa.Column(
            "allowed_languages",
            JSONB(),
            nullable=False,
            server_default="'[]'::jsonb",
        ),
    )


def downgrade():
    op.drop_column("bot_configs", "allowed_languages")
