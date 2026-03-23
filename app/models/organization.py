import uuid
from decimal import Decimal
from datetime import datetime

from sqlalchemy import DateTime, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class Organization(Base):
    """Organization model.

    settings JSONB schema supports these keys:
      {
        "business_hours": {
          "enabled": true, "start": "09:00", "end": "19:00",
          "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
          "timezone": "Asia/Kolkata"
        },
        "rate_limits": {
          "daily_cap": 5, "hourly_cap": 2, "cooldown_seconds": 60
        }
      }

    Usage:
      business_hours = org.settings.get("business_hours", {})
      rate_limits = org.settings.get("rate_limits", {})
    """
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    # Telephony credentials (org-level)
    plivo_auth_id: Mapped[str | None] = mapped_column(Text)
    plivo_auth_token: Mapped[str | None] = mapped_column(Text)
    twilio_account_sid: Mapped[str | None] = mapped_column(Text)
    twilio_auth_token: Mapped[str | None] = mapped_column(Text)
    # GHL credentials (org-level)
    ghl_api_key: Mapped[str | None] = mapped_column(Text)
    ghl_location_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
