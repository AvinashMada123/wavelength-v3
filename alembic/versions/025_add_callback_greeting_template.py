"""Add callback_greeting_template to bot_configs."""

from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bot_configs",
        sa.Column("callback_greeting_template", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("bot_configs", "callback_greeting_template")
