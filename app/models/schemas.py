from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Goal Config schemas ---


class RedFlagConfig(BaseModel):
    id: str
    label: str
    severity: Literal["critical", "high", "medium", "low"]
    auto_detect: bool = False
    keywords: list[str] | None = None
    detect_in: Literal["realtime", "post_call"] = "post_call"

    @model_validator(mode="after")
    def realtime_needs_keywords(self):
        if self.detect_in == "realtime" and not self.keywords:
            raise ValueError(
                f"Red flag '{self.id}': detect_in='realtime' requires non-empty keywords list"
            )
        return self


class SuccessCriterion(BaseModel):
    id: str
    label: str
    is_primary: bool = False


class DataCaptureField(BaseModel):
    id: str
    label: str
    type: Literal["string", "integer", "float", "boolean", "enum"]
    enum_values: list[str] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def enum_needs_values(self):
        if self.type == "enum" and not self.enum_values:
            raise ValueError(
                f"Field '{self.id}': type='enum' requires non-empty enum_values"
            )
        return self


class GoalConfig(BaseModel):
    version: int = 1
    goal_type: str
    goal_description: str
    success_criteria: list[SuccessCriterion]
    red_flags: list[RedFlagConfig] = []
    data_capture_fields: list[DataCaptureField] = []

    @model_validator(mode="after")
    def exactly_one_primary(self):
        primaries = [c for c in self.success_criteria if c.is_primary]
        if len(primaries) == 0:
            raise ValueError("Exactly one success criterion must have is_primary=True, found 0")
        if len(primaries) > 1:
            ids = [c.id for c in primaries]
            raise ValueError(
                f"Exactly one success criterion must have is_primary=True, found {len(primaries)}: {ids}"
            )
        return self

    @model_validator(mode="after")
    def unique_ids_across_all(self):
        all_ids: list[str] = []
        for c in self.success_criteria:
            all_ids.append(c.id)
        for rf in self.red_flags:
            all_ids.append(rf.id)
        for f in self.data_capture_fields:
            all_ids.append(f.id)
        seen = set()
        for item_id in all_ids:
            if item_id in seen:
                raise ValueError(f"Duplicate ID '{item_id}' found across criteria, red flags, and fields")
            seen.add(item_id)
        return self


# --- Call Analysis schemas (output of post-call analyzer) ---


class RedFlagDetection(BaseModel):
    id: str
    severity: str
    evidence: str | None = None
    turn_index: int | None = None


class CallAnalysis(BaseModel):
    goal_outcome: str | None = None
    summary: str | None = None
    interest_level: str | None = None
    red_flags: list[RedFlagDetection] = []
    captured_data: dict[str, Any] = {}


# --- Request schemas ---


class TriggerCallRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    bot_id: uuid.UUID
    contact_name: str
    contact_phone: str
    ghl_contact_id: str | None = None
    extra_vars: dict[str, str] = Field(default_factory=dict)

    def merged_extra_vars(self) -> dict[str, str]:
        merged = dict(self.extra_vars)
        for key, value in (self.model_extra or {}).items():
            if value is None or key in merged:
                continue
            if isinstance(value, (str, int, float, bool)):
                merged[key] = str(value)
        return merged


class CreateBotConfigRequest(BaseModel):
    agent_name: str
    company_name: str
    location: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    greeting_template: str | None = None
    stt_provider: str = "deepgram"
    tts_provider: str = "gemini"
    tts_voice: str = "Kore"
    tts_style_prompt: str | None = None
    llm_provider: Literal["google", "groq"] = "google"
    llm_model: str = "gemini-2.5-flash"
    language: str = "en-IN"
    system_prompt_template: str
    context_variables: dict[str, str] = Field(default_factory=dict)
    silence_timeout_secs: int = 5
    ghl_webhook_url: str | None = None
    ghl_api_key: str | None = None
    ghl_location_id: str | None = None
    ghl_post_call_tag: str | None = None
    ghl_workflows: list[dict] = Field(default_factory=list)
    max_call_duration: int = 480
    telephony_provider: str = "plivo"
    plivo_auth_id: str | None = None
    plivo_auth_token: str | None = None
    plivo_caller_id: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    phone_number_id: uuid.UUID | None = None
    goal_config: GoalConfig | None = None


class UpdateBotConfigRequest(BaseModel):
    agent_name: str | None = None
    company_name: str | None = None
    location: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    greeting_template: str | None = None
    stt_provider: str | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None
    tts_style_prompt: str | None = None
    llm_provider: Literal["google", "groq"] | None = None
    llm_model: str | None = None
    language: str | None = None
    system_prompt_template: str | None = None
    context_variables: dict[str, str] | None = None
    silence_timeout_secs: int | None = None
    ghl_webhook_url: str | None = None
    ghl_api_key: str | None = None
    ghl_location_id: str | None = None
    ghl_post_call_tag: str | None = None
    ghl_workflows: list[dict] | None = None
    max_call_duration: int | None = None
    telephony_provider: str | None = None
    plivo_auth_id: str | None = None
    plivo_auth_token: str | None = None
    plivo_caller_id: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    phone_number_id: uuid.UUID | None = None
    goal_config: GoalConfig | dict | None = None
    is_active: bool | None = None


# --- Response schemas ---


class TriggerCallResponse(BaseModel):
    call_sid: str
    status: str


class BotConfigResponse(BaseModel):
    id: uuid.UUID
    agent_name: str
    company_name: str
    location: str | None
    event_name: str | None
    event_date: str | None
    event_time: str | None
    greeting_template: str | None = None
    stt_provider: str
    tts_provider: str
    tts_voice: str
    tts_style_prompt: str | None
    llm_provider: str
    llm_model: str
    language: str
    system_prompt_template: str
    context_variables: dict[str, str]
    silence_timeout_secs: int
    ghl_webhook_url: str | None
    ghl_api_key: str | None
    ghl_location_id: str | None
    ghl_post_call_tag: str | None
    ghl_workflows: list[dict]
    max_call_duration: int
    telephony_provider: str
    plivo_caller_id: str | None = None
    twilio_phone_number: str | None = None
    phone_number_id: uuid.UUID | None = None
    goal_config: dict | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CallLogListResponse(BaseModel):
    """Light response for list endpoints — no metadata/transcript."""
    id: uuid.UUID
    bot_id: uuid.UUID
    call_sid: str
    contact_name: str
    contact_phone: str
    ghl_contact_id: str | None
    status: str
    outcome: str | None
    call_duration: int | None
    summary: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallAnalyticsResponse(BaseModel):
    """Analytics data attached to a call log detail."""
    goal_outcome: str | None = None
    goal_type: str | None = None
    red_flags: list[dict] | None = None
    has_red_flags: bool = False
    red_flag_max_severity: str | None = None
    captured_data: dict | None = None
    turn_count: int | None = None
    agent_word_share: float | None = None


class CallLogResponse(BaseModel):
    """Full response with metadata — for single call detail."""
    id: uuid.UUID
    bot_id: uuid.UUID
    call_sid: str
    contact_name: str
    contact_phone: str
    ghl_contact_id: str | None
    status: str
    outcome: str | None
    call_duration: int | None
    summary: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    analytics: CallAnalyticsResponse | None = None

    model_config = {"from_attributes": True}


# --- Queue & Circuit Breaker schemas ---


class QueuedCallResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    contact_name: str
    contact_phone: str
    ghl_contact_id: str | None
    extra_vars: dict
    source: str
    status: str
    priority: int
    error_message: str | None
    call_log_id: uuid.UUID | None
    created_at: datetime
    processed_at: datetime | None
    bot_name: str | None = None

    model_config = {"from_attributes": True}


class CircuitBreakerResponse(BaseModel):
    bot_id: uuid.UUID
    bot_name: str | None = None
    state: str
    consecutive_failures: int
    failure_threshold: int
    last_failure_at: datetime | None
    last_failure_reason: str | None
    opened_at: datetime | None
    opened_by: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class QueueStatsResponse(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    queued: int = 0
    held: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class QueueEnqueueResponse(BaseModel):
    queue_id: uuid.UUID
    status: str


# --- Internal data classes ---


class CallContext:
    """Per-call context passed to the pipeline. Constructed from DB call_log + bot_config."""

    def __init__(
        self,
        call_sid: str,
        filled_prompt: str,
        contact_name: str,
        ghl_contact_id: str | None,
        ghl_webhook_url: str | None,
        tts_provider: str,
        tts_voice: str,
        tts_style_prompt: str | None,
        language: str,
        silence_timeout_secs: int,
        bot_id: str,
        # Set by WebSocket handler before pipeline start
        websocket: object | None = None,
        stream_id: str | None = None,
        # Full bot config for credentials
        bot_config: object | None = None,
    ):
        self.call_sid = call_sid
        self.filled_prompt = filled_prompt
        self.contact_name = contact_name
        self.ghl_contact_id = ghl_contact_id
        self.ghl_webhook_url = ghl_webhook_url
        self.tts_provider = tts_provider
        self.tts_voice = tts_voice
        self.tts_style_prompt = tts_style_prompt
        self.language = language
        self.silence_timeout_secs = silence_timeout_secs
        self.bot_id = bot_id
        self.websocket = websocket
        self.stream_id = stream_id
        self.bot_config = bot_config

    @classmethod
    def from_db(cls, call_log, bot_config=None) -> CallContext:
        """Reconstruct CallContext from a CallLog row and optional BotConfig."""
        cd = call_log.context_data or {}
        return cls(
            call_sid=call_log.call_sid,
            filled_prompt=cd.get("filled_prompt", ""),
            contact_name=cd.get("contact_name", call_log.contact_name),
            ghl_contact_id=cd.get("ghl_contact_id", call_log.ghl_contact_id),
            ghl_webhook_url=cd.get("ghl_webhook_url"),
            tts_provider=cd.get("tts_provider", "gemini"),
            tts_voice=cd.get("tts_voice", "Kore"),
            tts_style_prompt=cd.get("tts_style_prompt"),
            language=cd.get("language", "en-IN"),
            silence_timeout_secs=cd.get("silence_timeout_secs", 5),
            bot_id=cd.get("bot_id", str(call_log.bot_id)),
            bot_config=bot_config,
        )
