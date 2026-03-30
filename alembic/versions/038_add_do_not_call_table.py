"""Add do_not_call table.

Revision ID: 038
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "do_not_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("phone_number", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_call_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.Column("manual_override", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial unique: one active DNC per phone per org
    op.create_index(
        "ix_dnc_org_phone_active",
        "do_not_call",
        ["org_id", "phone_number"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    # Fast lookup index
    op.create_index(
        "ix_dnc_org_phone_removed",
        "do_not_call",
        ["org_id", "phone_number", "removed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dnc_org_phone_removed", table_name="do_not_call")
    op.drop_index("ix_dnc_org_phone_active", table_name="do_not_call")
    op.drop_table("do_not_call")
