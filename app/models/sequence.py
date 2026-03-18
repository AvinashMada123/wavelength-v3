"""Sequence engine models — templates, steps, instances, touchpoints."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class SequenceTemplate(Base):
    __tablename__ = "sequence_templates"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_seqtemplate_org_name"),
        Index("ix_seqtemplate_org", "org_id"),
        Index("ix_seqtemplate_bot_active", "bot_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    max_active_per_lead: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    variables: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint("template_id", "step_order", name="uq_seqstep_template_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_templates.id", ondelete="RESTRICT"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    timing_type: Mapped[str] = mapped_column(Text, nullable=False)
    timing_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    skip_conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp_template_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_template_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=True
    )
    expects_reply: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    reply_handler: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceInstance(Base):
    __tablename__ = "sequence_instances"
    __table_args__ = (
        Index("ix_seqinst_lead", "lead_id"),
        Index("ix_seqinst_org_status", "org_id", "status"),
        Index("ix_seqinst_template_status", "template_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_templates.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    trigger_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_logs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    context_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceTouchpoint(Base):
    __tablename__ = "sequence_touchpoints"
    __table_args__ = (
        Index("ix_seqtp_instance_order", "instance_id", "step_order"),
        Index("ix_seqtp_lead_status", "lead_id", "status"),
        Index("ix_seqtp_org_status_scheduled", "org_id", "status", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_instances.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_steps.id", ondelete="SET NULL"), nullable=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_snapshot: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    session_window_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    messaging_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messaging_providers.id"), nullable=True
    )
    queued_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_queue.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)
