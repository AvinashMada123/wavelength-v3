"""Add ambient_sound and ambient_sound_volume to bot_configs.

Revision ID: 037
Revises: 036
"""

from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("ambient_sound", sa.Text(), nullable=True))
    op.add_column(
        "bot_configs", sa.Column("ambient_sound_volume", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "ambient_sound_volume")
    op.drop_column("bot_configs", "ambient_sound")
