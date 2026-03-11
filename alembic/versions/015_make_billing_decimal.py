"""Change billing balances and transactions to decimal credits.

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "credit_balance",
        existing_type=sa.Integer(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using="credit_balance::numeric(12,2)",
        server_default="0",
    )
    op.alter_column(
        "credit_transactions",
        "amount",
        existing_type=sa.Integer(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using="amount::numeric(12,2)",
    )
    op.alter_column(
        "credit_transactions",
        "balance_after",
        existing_type=sa.Integer(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using="balance_after::numeric(12,2)",
    )


def downgrade() -> None:
    op.alter_column(
        "credit_transactions",
        "balance_after",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(balance_after)::integer",
    )
    op.alter_column(
        "credit_transactions",
        "amount",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(amount)::integer",
    )
    op.alter_column(
        "organizations",
        "credit_balance",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(credit_balance)::integer",
        server_default="0",
    )
