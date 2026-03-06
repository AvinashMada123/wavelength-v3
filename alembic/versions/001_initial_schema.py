"""Initial schema: bot_configs and call_logs tables.

Revision ID: 001
Revises: None
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bot_configs
    op.create_table(
        "bot_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Text(), nullable=True),
        sa.Column("event_time", sa.Text(), nullable=True),
        sa.Column("tts_voice", sa.Text(), nullable=False, server_default="en-IN-Chirp3-HD-Kore"),
        sa.Column("system_prompt_template", sa.Text(), nullable=False),
        sa.Column("silence_timeout_secs", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("ghl_webhook_url", sa.Text(), nullable=True),
        sa.Column("plivo_auth_id", sa.Text(), nullable=False),
        sa.Column("plivo_auth_token", sa.Text(), nullable=False),
        sa.Column("plivo_caller_id", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_bot_configs_active", "bot_configs", ["id"], postgresql_where=sa.text("is_active = true"))

    # call_logs
    op.create_table(
        "call_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=False),
        sa.Column("call_sid", sa.Text(), unique=True, nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=False),
        sa.Column("ghl_contact_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="initiated"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("call_duration", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("plivo_call_uuid", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("context_data", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("idx_call_logs_bot_id", "call_logs", ["bot_id"])
    op.create_index("idx_call_logs_call_sid", "call_logs", ["call_sid"], unique=True)
    op.create_index("idx_call_logs_status", "call_logs", ["status"])
    op.create_index("idx_call_logs_created", "call_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("call_logs")
    op.drop_table("bot_configs")
