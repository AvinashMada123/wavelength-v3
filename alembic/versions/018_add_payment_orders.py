"""Add payment_orders table for Cashfree payment tracking.

Revision ID: 018
Revises: 017
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.Text(), unique=True, nullable=False),
        sa.Column("cf_order_id", sa.Text(), nullable=True),
        sa.Column("amount_inr", sa.Numeric(12, 2), nullable=False),
        sa.Column("credits", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("payment_method", sa.Text(), nullable=True),
        sa.Column("cf_payment_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_payment_orders_org_created",
        "payment_orders",
        ["org_id", "created_at"],
    )
    op.create_index(
        "idx_payment_orders_order_id",
        "payment_orders",
        ["order_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("payment_orders")
