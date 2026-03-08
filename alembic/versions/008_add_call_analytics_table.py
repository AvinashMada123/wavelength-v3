"""Add call_analytics table for goal-based analytics.

Revision ID: 008
Revises: 007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_analytics",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("call_log_id", UUID(as_uuid=True), unique=True, nullable=True),
        sa.Column("bot_id", UUID(as_uuid=True), nullable=False),
        sa.Column("goal_type", sa.String, nullable=True),
        sa.Column("goal_outcome", sa.String, nullable=True),
        sa.Column("has_red_flags", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("red_flag_max_severity", sa.String, nullable=True),
        sa.Column("red_flags", JSONB, nullable=True),
        sa.Column("captured_data", JSONB, nullable=True),
        sa.Column("turn_count", sa.Integer, nullable=True),
        sa.Column("call_duration_secs", sa.Integer, nullable=True),
        sa.Column("agent_word_share", sa.Float, nullable=True),
        sa.Column("analysis_input_tokens", sa.Integer, nullable=True),
        sa.Column("analysis_output_tokens", sa.Integer, nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Text, nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Core lookup indexes
    op.create_index("ix_analytics_bot_outcome", "call_analytics", ["bot_id", "goal_outcome"])
    op.create_index("ix_analytics_bot_redflags", "call_analytics", ["bot_id", "has_red_flags"])

    # Time-series trends
    op.create_index("ix_analytics_bot_created_outcome", "call_analytics", ["bot_id", "created_at", "goal_outcome"])

    # Red flag dashboard
    op.create_index("ix_analytics_bot_severity_created", "call_analytics", ["bot_id", "red_flag_max_severity", "created_at"])

    # Partial index for unacknowledged alerts
    op.create_index(
        "ix_analytics_unacked_alerts",
        "call_analytics",
        ["bot_id", "has_red_flags", "acknowledged_at", "snoozed_until"],
        postgresql_where=sa.text("has_red_flags = true AND acknowledged_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_unacked_alerts", table_name="call_analytics")
    op.drop_index("ix_analytics_bot_severity_created", table_name="call_analytics")
    op.drop_index("ix_analytics_bot_created_outcome", table_name="call_analytics")
    op.drop_index("ix_analytics_bot_redflags", table_name="call_analytics")
    op.drop_index("ix_analytics_bot_outcome", table_name="call_analytics")
    op.drop_table("call_analytics")
