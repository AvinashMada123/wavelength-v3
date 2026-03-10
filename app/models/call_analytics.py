import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class CallAnalytics(Base):
    __tablename__ = "call_analytics"
    __table_args__ = (
        Index("ix_analytics_bot_outcome", "bot_id", "goal_outcome"),
        Index("ix_analytics_bot_redflags", "bot_id", "has_red_flags"),
        Index("ix_analytics_bot_created_outcome", "bot_id", "created_at", "goal_outcome"),
        Index("ix_analytics_bot_severity_created", "bot_id", "red_flag_max_severity", "created_at"),
        # Partial index for unacknowledged alerts — used by GET /alerts endpoint
        Index(
            "ix_analytics_unacked_alerts",
            "bot_id",
            "has_red_flags",
            "acknowledged_at",
            "snoozed_until",
            postgresql_where=text("has_red_flags = true AND acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Goal outcome
    goal_type: Mapped[str | None] = mapped_column(String)
    goal_outcome: Mapped[str | None] = mapped_column(String)

    # Red flags
    has_red_flags: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    red_flag_max_severity: Mapped[str | None] = mapped_column(String)
    red_flags: Mapped[dict | None] = mapped_column(JSONB)

    # Captured data
    captured_data: Mapped[dict | None] = mapped_column(JSONB)

    # Conversation quality metrics
    turn_count: Mapped[int | None] = mapped_column(Integer)
    call_duration_secs: Mapped[int | None] = mapped_column(Integer)
    agent_word_share: Mapped[float | None] = mapped_column(Float)

    # Cost tracking (split for accurate cost calculation)
    analysis_input_tokens: Mapped[int | None] = mapped_column(Integer)
    analysis_output_tokens: Mapped[int | None] = mapped_column(Integer)

    # Alert management
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(Text)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
