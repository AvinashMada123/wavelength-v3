"""Add call_queue and circuit_breaker_state tables for call gating system.

Revision ID: 006
Revises: 005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Call queue — holds incoming calls until approved/processed
    op.create_table(
        "call_queue",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=False),
        sa.Column("ghl_contact_id", sa.Text(), nullable=True),
        sa.Column("extra_vars", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source", sa.Text(), server_default="webhook", nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("call_log_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_call_queue_bot_id", "call_queue", ["bot_id"])
    op.create_index("idx_call_queue_status", "call_queue", ["status"])
    op.create_index("idx_call_queue_created", "call_queue", ["created_at"])

    # Circuit breaker state — per-bot circuit breaker
    op.create_table(
        "circuit_breaker_state",
        sa.Column("bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), primary_key=True),
        sa.Column("state", sa.Text(), server_default="closed", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_threshold", sa.Integer(), server_default="3", nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_reason", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("circuit_breaker_state")
    op.drop_index("idx_call_queue_created", table_name="call_queue")
    op.drop_index("idx_call_queue_status", table_name="call_queue")
    op.drop_index("idx_call_queue_bot_id", table_name="call_queue")
    op.drop_table("call_queue")
