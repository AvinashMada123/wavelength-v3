from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --- Request schemas ---


class TriggerCallRequest(BaseModel):
    bot_id: uuid.UUID
    contact_name: str
    contact_phone: str
    ghl_contact_id: str | None = None
    extra_vars: dict[str, str] = Field(default_factory=dict)


class CreateBotConfigRequest(BaseModel):
    agent_name: str
    company_name: str
    location: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    tts_voice: str = "Kore"
    tts_style_prompt: str | None = None
    system_prompt_template: str
    silence_timeout_secs: int = 5
    ghl_webhook_url: str | None = None
    plivo_auth_id: str
    plivo_auth_token: str
    plivo_caller_id: str


class UpdateBotConfigRequest(BaseModel):
    agent_name: str | None = None
    company_name: str | None = None
    location: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    tts_voice: str | None = None
    tts_style_prompt: str | None = None
    system_prompt_template: str | None = None
    silence_timeout_secs: int | None = None
    ghl_webhook_url: str | None = None
    plivo_auth_id: str | None = None
    plivo_auth_token: str | None = None
    plivo_caller_id: str | None = None
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
    tts_voice: str
    tts_style_prompt: str | None
    system_prompt_template: str
    silence_timeout_secs: int
    ghl_webhook_url: str | None
    plivo_caller_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CallLogResponse(BaseModel):
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
        tts_voice: str,
        tts_style_prompt: str | None,
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
        self.tts_voice = tts_voice
        self.tts_style_prompt = tts_style_prompt
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
            tts_voice=cd.get("tts_voice", "Kore"),
            tts_style_prompt=cd.get("tts_style_prompt"),
            silence_timeout_secs=cd.get("silence_timeout_secs", 5),
            bot_id=cd.get("bot_id", str(call_log.bot_id)),
            bot_config=bot_config,
        )
