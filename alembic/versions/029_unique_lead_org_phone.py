"""Make (org_id, phone_number) unique on leads table.

Closes a TOCTOU race in create_lead where two concurrent requests could
both pass the duplicate check SELECT before either INSERT committed.
"""

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("idx_leads_org_phone", table_name="leads")
    op.create_index(
        "idx_leads_org_phone",
        "leads",
        ["org_id", "phone_number"],
        unique=True,
    )


def downgrade():
    op.drop_index("idx_leads_org_phone", table_name="leads")
    op.create_index(
        "idx_leads_org_phone",
        "leads",
        ["org_id", "phone_number"],
        unique=False,
    )
