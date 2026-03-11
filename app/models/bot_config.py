import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
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
    stt_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="deepgram")
    tts_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="gemini")
    tts_voice: Mapped[str] = mapped_column(Text, nullable=False, server_default="Kore")
    tts_style_prompt: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en-IN")
    system_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    context_variables: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    silence_timeout_secs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    ghl_webhook_url: Mapped[str | None] = mapped_column(Text)
    ghl_api_key: Mapped[str | None] = mapped_column(Text)
    ghl_location_id: Mapped[str | None] = mapped_column(Text)
    ghl_post_call_tag: Mapped[str | None] = mapped_column(Text)
    ghl_workflows: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    max_call_duration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="480")
    telephony_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="plivo")
    plivo_auth_id: Mapped[str | None] = mapped_column(Text)
    plivo_auth_token: Mapped[str | None] = mapped_column(Text)
    plivo_caller_id: Mapped[str | None] = mapped_column(Text)
    twilio_account_sid: Mapped[str | None] = mapped_column(Text)
    twilio_auth_token: Mapped[str | None] = mapped_column(Text)
    twilio_phone_number: Mapped[str | None] = mapped_column(Text)
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True
    )
    greeting_template: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="google")
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="gemini-2.5-flash")
    llm_thinking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    goal_config: Mapped[dict | None] = mapped_column(JSONB)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
