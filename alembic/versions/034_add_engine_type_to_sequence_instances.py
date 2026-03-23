"""add engine_type to sequence_instances

Revision ID: 034
Revises: 033
"""

from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sequence_instances",
        sa.Column("engine_type", sa.Text(), server_default=sa.text("'linear'"), nullable=False),
    )
    op.create_index(
        "ix_seqinst_engine_type_status",
        "sequence_instances",
        ["engine_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_seqinst_engine_type_status", table_name="sequence_instances")
    op.drop_column("sequence_instances", "engine_type")
