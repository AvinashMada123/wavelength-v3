"""Add call memory fields to bot_configs."""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bot_configs",
        sa.Column("call_memory_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "bot_configs",
        sa.Column("call_memory_count", sa.Integer(), nullable=False, server_default="3"),
    )
    # Add index on call_logs for efficient phone+org lookups used by call memory
    op.create_index(
        "idx_call_logs_org_phone",
        "call_logs",
        ["org_id", "contact_phone"],
    )


def downgrade():
    op.drop_index("idx_call_logs_org_phone", table_name="call_logs")
    op.drop_column("bot_configs", "call_memory_count")
    op.drop_column("bot_configs", "call_memory_enabled")
