"""Add campaign_id and campaign_lead_id to call_queue

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_queue",
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=True),
    )
    op.add_column(
        "call_queue",
        sa.Column("campaign_lead_id", UUID(as_uuid=True), sa.ForeignKey("campaign_leads.id"), nullable=True),
    )
    op.create_index("idx_call_queue_campaign_id", "call_queue", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("idx_call_queue_campaign_id", table_name="call_queue")
    op.drop_column("call_queue", "campaign_lead_id")
    op.drop_column("call_queue", "campaign_id")
