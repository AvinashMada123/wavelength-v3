import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class CallLog(Base):
    __tablename__ = "call_logs"
    __table_args__ = (
        Index("idx_call_logs_bot_id", "bot_id"),
        Index("idx_call_logs_call_sid", "call_sid", unique=True),
        Index("idx_call_logs_status", "status"),
        Index("idx_call_logs_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    call_sid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    contact_name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[str] = mapped_column(Text, nullable=False)
    ghl_contact_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="initiated")
    outcome: Mapped[str | None] = mapped_column(Text)
    call_duration: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    plivo_call_uuid: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    context_data: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
