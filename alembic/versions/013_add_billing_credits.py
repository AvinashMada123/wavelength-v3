"""Add billing/credits system: credit_balance on organizations, credit_transactions table.

Revision ID: 013
Revises: 012
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === 1. Add credit_balance column to organizations ===
    op.add_column(
        "organizations",
        sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="0"),
    )

    # === 2. Create credit_transactions table ===
    op.create_table(
        "credit_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_credit_transactions_org_created",
        "credit_transactions",
        ["org_id", "created_at"],
    )

    # === 3. Give all existing organizations 1000 free starting credits ===
    op.execute("UPDATE organizations SET credit_balance = 1000")

    # Insert a matching transaction record for each existing org so ledger is consistent
    op.execute(
        """
        INSERT INTO credit_transactions (org_id, amount, balance_after, type, description)
        SELECT id, 1000, 1000, 'topup', 'Welcome bonus — 1000 free credits'
        FROM organizations
        """
    )


def downgrade() -> None:
    op.drop_table("credit_transactions")
    op.drop_column("organizations", "credit_balance")
