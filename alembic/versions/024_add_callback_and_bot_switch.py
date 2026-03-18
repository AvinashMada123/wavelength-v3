"""Add callback scheduling and bot switch fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    # Bot config: callback settings
    op.add_column(
        "bot_configs",
        sa.Column("callback_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("callback_retry_delay_hours", sa.Float(), nullable=False, server_default="2.0"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("callback_max_retries", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("callback_timezone", sa.Text(), nullable=False, server_default="Asia/Kolkata"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("callback_window_start", sa.Integer(), nullable=False, server_default="9"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("callback_window_end", sa.Integer(), nullable=False, server_default="20"),
    )
    # Bot config: bot switch targets
    op.add_column(
        "bot_configs",
        sa.Column("bot_switch_targets", sa.JSON(), nullable=False, server_default="[]"),
    )
    # Call queue: scheduling fields
    op.add_column(
        "call_queue",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "call_queue",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_queue",
        sa.Column("original_call_sid", sa.Text(), nullable=True),
    )
    # Index for efficient scheduled call queries
    op.create_index(
        "idx_call_queue_scheduled",
        "call_queue",
        ["status", "scheduled_at"],
    )


def downgrade():
    op.drop_index("idx_call_queue_scheduled", table_name="call_queue")
    op.drop_column("call_queue", "original_call_sid")
    op.drop_column("call_queue", "retry_count")
    op.drop_column("call_queue", "scheduled_at")
    op.drop_column("bot_configs", "bot_switch_targets")
    op.drop_column("bot_configs", "callback_window_end")
    op.drop_column("bot_configs", "callback_window_start")
    op.drop_column("bot_configs", "callback_timezone")
    op.drop_column("bot_configs", "callback_max_retries")
    op.drop_column("bot_configs", "callback_retry_delay_hours")
    op.drop_column("bot_configs", "callback_enabled")
