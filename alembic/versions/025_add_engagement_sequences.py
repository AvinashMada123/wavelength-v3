"""Add engagement sequence engine tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    # --- messaging_providers ---
    op.create_table(
        "messaging_providers",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("credentials", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_msgprov_org", "messaging_providers", ["org_id"])
    op.create_index("ix_msgprov_org_type", "messaging_providers", ["org_id", "provider_type"])

    # --- sequence_templates ---
    op.create_table(
        "sequence_templates",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("trigger_conditions", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_active_per_lead", sa.Integer(), server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_seqtemplate_org_name", "sequence_templates", ["org_id", "name"])
    op.create_index("ix_seqtemplate_org", "sequence_templates", ["org_id"])
    op.create_index("ix_seqtemplate_bot_active", "sequence_templates", ["bot_id", "is_active"])

    # --- sequence_steps ---
    op.create_table(
        "sequence_steps",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("sequence_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("timing_type", sa.Text(), nullable=False),
        sa.Column("timing_value", JSONB(), nullable=False),
        sa.Column("skip_conditions", JSONB(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("whatsapp_template_name", sa.Text(), nullable=True),
        sa.Column("whatsapp_template_params", JSONB(), nullable=True),
        sa.Column("ai_prompt", sa.Text(), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("voice_bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=True),
        sa.Column("expects_reply", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("reply_handler", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_seqstep_template_order", "sequence_steps", ["template_id", "step_order"])

    # --- sequence_instances ---
    op.create_table(
        "sequence_instances",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("sequence_templates.id"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("trigger_call_id", UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'")),
        sa.Column("context_data", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_seqinst_lead", "sequence_instances", ["lead_id"])
    op.create_index("ix_seqinst_org_status", "sequence_instances", ["org_id", "status"])
    op.create_index("ix_seqinst_template_status", "sequence_instances", ["template_id", "status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_seqinst_active_per_lead "
        "ON sequence_instances (template_id, lead_id) "
        "WHERE status = 'active'"
    )

    # --- sequence_touchpoints ---
    op.create_table(
        "sequence_touchpoints",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("sequence_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("sequence_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_snapshot", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("reply_response", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2")),
        sa.Column("messaging_provider_id", UUID(as_uuid=True), sa.ForeignKey("messaging_providers.id"), nullable=True),
        sa.Column("queued_call_id", UUID(as_uuid=True), sa.ForeignKey("call_queue.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_seqtp_instance_order", "sequence_touchpoints", ["instance_id", "step_order"])
    op.create_index("ix_seqtp_lead_status", "sequence_touchpoints", ["lead_id", "status"])
    op.create_index("ix_seqtp_org_status_scheduled", "sequence_touchpoints", ["org_id", "status", "scheduled_at"])


def downgrade():
    op.drop_table("sequence_touchpoints")
    op.execute("DROP INDEX IF EXISTS uq_seqinst_active_per_lead")
    op.drop_table("sequence_instances")
    op.drop_table("sequence_steps")
    op.drop_table("sequence_templates")
    op.drop_table("messaging_providers")
