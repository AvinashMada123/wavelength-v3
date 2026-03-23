"""Flow builder models — definitions, versions, nodes, edges, instances, touchpoints, transitions, events."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class FlowDefinition(Base):
    """Top-level flow template. Replaces SequenceTemplate for flow-based sequences."""

    __tablename__ = "flow_definitions"
    __table_args__ = (
        Index("ix_flowdef_org", "org_id"),
        Index("ix_flowdef_org_active", "org_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)  # post_call, manual, campaign_complete
    trigger_conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    max_active_per_lead: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    variables: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowVersion(Base):
    """Immutable published snapshot. Leads are pinned to the version they enrolled on."""

    __tablename__ = "flow_versions"
    __table_args__ = (
        Index("ix_flowver_flow", "flow_id"),
        Index("ix_flowver_flow_status", "flow_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # draft, published, archived
    is_locked: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True  # FK to users table if needed
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FlowNode(Base):
    """A node in the flow graph. org_id denormalized for efficient RLS queries."""

    __tablename__ = "flow_nodes"
    __table_args__ = (
        Index("ix_flownode_version", "version_id"),
        Index("ix_flownode_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    # node_type values: voice_call, whatsapp_template, whatsapp_session, ai_generate_send,
    #   condition, delay_wait, wait_for_event, goal_met, end
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    position_y: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FlowEdge(Base):
    """Directed edge between two nodes. condition_label determines which outcome follows this edge."""

    __tablename__ = "flow_edges"
    __table_args__ = (
        Index("ix_flowedge_version", "version_id"),
        Index("ix_flowedge_source", "source_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    condition_label: Mapped[str] = mapped_column(Text, nullable=False)  # picked_up, no_answer, default, etc.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class FlowInstance(Base):
    """A lead's journey through a flow. Pinned to a specific FlowVersion at enrollment."""

    __tablename__ = "flow_instances"
    __table_args__ = (
        Index("ix_flowinst_lead", "lead_id"),
        Index("ix_flowinst_org_status", "org_id", "status"),
        Index("ix_flowinst_flow_status", "flow_id", "status"),
        # Only one active instance per lead per flow
        Index(
            "uq_flowinst_flow_lead_active",
            "flow_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_definitions.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    trigger_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_logs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    # status values: active, paused, completed, cancelled, error
    current_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=True
    )
    context_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowTouchpoint(Base):
    """Execution record for each node visit. Extends the concept of SequenceTouchpoint."""

    __tablename__ = "flow_touchpoints"
    __table_args__ = (
        Index("ix_flowtp_instance", "instance_id"),
        Index("ix_flowtp_org_status_scheduled", "org_id", "status", "scheduled_at"),
        Index("ix_flowtp_lead_org", "lead_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    node_snapshot: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    # status values: pending, executing, waiting, completed, failed, skipped
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    # outcome values: picked_up, no_answer, busy, replied, timed_out, failed, etc.
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    messaging_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messaging_providers.id"), nullable=True
    )
    queued_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_queue.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowTransition(Base):
    """Audit trail for journey replay and debugging."""

    __tablename__ = "flow_transitions"
    __table_args__ = (
        Index("ix_flowtrans_instance", "instance_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    from_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=True  # null for entry transition
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_edges.id"), nullable=True
    )
    outcome_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    transitioned_at: Mapped[datetime] = mapped_column(nullable=False)


class FlowEvent(Base):
    """Event delivery mechanism for 'Wait for Event' nodes."""

    __tablename__ = "flow_events"
    __table_args__ = (
        Index("ix_flowevent_instance_consumed", "instance_id", "consumed"),
        Index("ix_flowevent_unconsumed", "consumed", "created_at",
              postgresql_where=text("consumed = false")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # event_type values: call_completed, reply_received, timeout, manual_advance
    event_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    consumed: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
