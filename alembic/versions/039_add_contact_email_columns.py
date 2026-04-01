"""Add contact_email to call_queue and call_logs.

Revision ID: 039
"""

from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_queue", sa.Column("contact_email", sa.Text(), nullable=True))
    op.add_column("call_logs", sa.Column("contact_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("call_logs", "contact_email")
    op.drop_column("call_queue", "contact_email")
