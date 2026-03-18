"""Add sequence_template_id to bot_configs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bot_configs",
        sa.Column("sequence_template_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bot_configs_sequence_template",
        "bot_configs",
        "sequence_templates",
        ["sequence_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_bot_configs_sequence_template", "bot_configs", type_="foreignkey")
    op.drop_column("bot_configs", "sequence_template_id")
