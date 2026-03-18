"""Add variables column to sequence_templates."""

from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sequence_templates",
        sa.Column("variables", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("sequence_templates", "variables")
