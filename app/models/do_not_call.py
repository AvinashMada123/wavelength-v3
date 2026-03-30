"""Do Not Call list — persistent, org-scoped phone block list."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class DoNotCall(Base):
    __tablename__ = "do_not_call"
    __table_args__ = (
        # Only one active DNC per phone per org
        Index(
            "ix_dnc_org_phone_active",
            "org_id",
            "phone_number",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        # Fast lookup for queue processor gate
        Index("ix_dnc_org_phone_removed", "org_id", "phone_number", "removed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # auto_transcript, manual_ui, manual_api
    source_call_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(Text)
