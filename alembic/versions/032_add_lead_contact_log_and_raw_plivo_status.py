"""Add lead_contact_log table and raw_plivo_status column.

Revision ID: 032
Revises: 031
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"


def upgrade():
    # lead_contact_log for persistent rate limiting
    op.execute("""
        CREATE TABLE IF NOT EXISTS lead_contact_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lead_id UUID NOT NULL,
            org_id UUID NOT NULL,
            channel VARCHAR(50) NOT NULL,
            contacted_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lead_contact_log_lookup
            ON lead_contact_log (lead_id, org_id, contacted_at DESC)
    """)

    # raw_plivo_status on call_logs (per spec §2.2)
    op.execute("""
        ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS raw_plivo_status VARCHAR(50)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_lead_contact_log_lookup")
    op.execute("DROP TABLE IF EXISTS lead_contact_log")
    op.execute("ALTER TABLE call_logs DROP COLUMN IF EXISTS raw_plivo_status")
