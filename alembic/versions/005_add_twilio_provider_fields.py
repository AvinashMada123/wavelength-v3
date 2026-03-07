"""Add telephony_provider and Twilio credential columns to bot_configs.

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("telephony_provider", sa.Text(), server_default="plivo", nullable=False),
    )
    op.add_column("bot_configs", sa.Column("twilio_account_sid", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("twilio_auth_token", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("twilio_phone_number", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_configs", "twilio_phone_number")
    op.drop_column("bot_configs", "twilio_auth_token")
    op.drop_column("bot_configs", "twilio_account_sid")
    op.drop_column("bot_configs", "telephony_provider")
