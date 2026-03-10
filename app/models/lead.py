import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("idx_leads_org_id", "org_id"),
        Index("idx_leads_org_phone", "org_id", "phone_number"),
        Index("idx_leads_org_status", "org_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    custom_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    qualification_level: Mapped[str | None] = mapped_column(Text)
    qualification_confidence: Mapped[float | None] = mapped_column(Float)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_call_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    ghl_contact_id: Mapped[str | None] = mapped_column(Text)
    bot_notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
