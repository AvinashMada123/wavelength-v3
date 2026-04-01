"""Add lead_engagements table.

Revision ID: 040
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("call_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), unique=True, nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("extraction_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("touchpoints", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("report_link", sa.Text(), nullable=True),
        sa.Column("ghl_contact_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_lead_engagements_org", "lead_engagements", ["org_id"])
    op.create_index("idx_lead_engagements_phone", "lead_engagements", ["contact_phone"])
    op.create_index("idx_lead_engagements_created", "lead_engagements", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_lead_engagements_created")
    op.drop_index("idx_lead_engagements_phone")
    op.drop_index("idx_lead_engagements_org")
    op.drop_table("lead_engagements")
