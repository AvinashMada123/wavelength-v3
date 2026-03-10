import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("idx_campaigns_org_id", "org_id"),
        Index("idx_campaigns_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    bot_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    total_leads: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_leads: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_leads: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignLead(Base):
    __tablename__ = "campaign_leads"
    __table_args__ = (
        Index("idx_campaign_leads_campaign", "campaign_id"),
        Index("idx_campaign_leads_status", "campaign_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    call_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
