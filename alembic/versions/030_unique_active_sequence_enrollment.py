"""Add partial unique index to prevent duplicate active sequence enrollments.

Only one active instance per (template_id, lead_id) is allowed.
Completed/cancelled instances don't block re-enrollment.
"""

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_seqinst_template_lead_active",
        "sequence_instances",
        ["template_id", "lead_id"],
        unique=True,
        postgresql_where="status = 'active'",
    )


def downgrade():
    op.drop_index("uq_seqinst_template_lead_active", table_name="sequence_instances")
