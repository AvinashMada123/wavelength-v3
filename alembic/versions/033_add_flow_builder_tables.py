"""Add flow builder tables: definitions, versions, nodes, edges, instances, touchpoints, transitions, events.

Revision ID: 033
Revises: 032
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- flow_definitions ---
    op.create_table(
        "flow_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("trigger_conditions", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("max_active_per_lead", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("variables", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowdef_org", "flow_definitions", ["org_id"])
    op.create_index("ix_flowdef_org_active", "flow_definitions", ["org_id", "is_active"])

    # --- flow_versions ---
    op.create_table(
        "flow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowver_flow", "flow_versions", ["flow_id"])
    op.create_index("ix_flowver_flow_status", "flow_versions", ["flow_id", "status"])

    # --- flow_nodes ---
    op.create_table(
        "flow_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position_x", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("position_y", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flownode_version", "flow_nodes", ["version_id"])
    op.create_index("ix_flownode_org", "flow_nodes", ["org_id"])

    # --- flow_edges ---
    op.create_table(
        "flow_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("condition_label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_flowedge_version", "flow_edges", ["version_id"])
    op.create_index("ix_flowedge_source", "flow_edges", ["source_node_id"])

    # --- flow_instances ---
    op.create_table(
        "flow_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_definitions.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("trigger_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("current_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=True),
        sa.Column("context_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowinst_lead", "flow_instances", ["lead_id"])
    op.create_index("ix_flowinst_org_status", "flow_instances", ["org_id", "status"])
    op.create_index("ix_flowinst_flow_status", "flow_instances", ["flow_id", "status"])
    op.create_index(
        "uq_flowinst_flow_lead_active",
        "flow_instances",
        ["flow_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # --- flow_touchpoints ---
    op.create_table(
        "flow_touchpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("node_snapshot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("messaging_provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messaging_providers.id"), nullable=True),
        sa.Column("queued_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_queue.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowtp_instance", "flow_touchpoints", ["instance_id"])
    op.create_index("ix_flowtp_org_status_scheduled", "flow_touchpoints", ["org_id", "status", "scheduled_at"])
    op.create_index("ix_flowtp_lead_org", "flow_touchpoints", ["lead_id", "org_id"])

    # --- flow_transitions ---
    op.create_table(
        "flow_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=True),
        sa.Column("to_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=False),
        sa.Column("edge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_edges.id"), nullable=True),
        sa.Column("outcome_data", postgresql.JSONB(), nullable=True),
        sa.Column("transitioned_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_flowtrans_instance", "flow_transitions", ["instance_id"])

    # --- flow_events ---
    op.create_table(
        "flow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("consumed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowevent_instance_consumed", "flow_events", ["instance_id", "consumed"])
    op.create_index(
        "ix_flowevent_unconsumed",
        "flow_events",
        ["consumed", "created_at"],
        postgresql_where=sa.text("consumed = false"),
    )


def downgrade() -> None:
    op.drop_table("flow_events")
    op.drop_table("flow_transitions")
    op.drop_table("flow_touchpoints")
    op.drop_table("flow_instances")
    op.drop_table("flow_edges")
    op.drop_table("flow_nodes")
    op.drop_table("flow_versions")
    op.drop_table("flow_definitions")
