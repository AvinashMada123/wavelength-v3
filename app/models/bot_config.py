import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BotConfig(Base):
    __tablename__ = "bot_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    event_name: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[str | None] = mapped_column(Text)
    tts_voice: Mapped[str] = mapped_column(Text, nullable=False, server_default="Kore")
    tts_style_prompt: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en-IN")
    system_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    context_variables: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    silence_timeout_secs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    ghl_webhook_url: Mapped[str | None] = mapped_column(Text)
    plivo_auth_id: Mapped[str] = mapped_column(Text, nullable=False)
    plivo_auth_token: Mapped[str] = mapped_column(Text, nullable=False)
    plivo_caller_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
