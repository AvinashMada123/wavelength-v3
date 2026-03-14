"""Add circuit_breaker_threshold to bot_configs

Revision ID: 020
Revises: 019
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column(
            "circuit_breaker_threshold",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "circuit_breaker_threshold")
