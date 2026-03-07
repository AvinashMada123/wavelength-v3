"""External webhook endpoint for triggering calls from GHL or other systems."""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.bot_config.loader import BotConfigLoader, fill_prompt_template
from app.config import settings
from app.database import get_db_session
from app.models.bot_config import BotConfig
from app.models.call_log import CallLog
from app.models.schemas import TriggerCallResponse
from app.plivo.client import make_outbound_call as plivo_make_call
from app.twilio.client import make_outbound_call as twilio_make_call

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# Set during app startup
bot_config_loader: BotConfigLoader | None = None


def set_dependencies(loader: BotConfigLoader):
    global bot_config_loader
    bot_config_loader = loader


def _verify_api_key(request: Request) -> None:
    """Verify x-api-key header or ?key= query param against WEBHOOK_API_KEY."""
    if not settings.WEBHOOK_API_KEY:
        raise HTTPException(status_code=500, detail="WEBHOOK_API_KEY not configured on server")

    api_key = request.headers.get("x-api-key") or request.query_params.get("key") or ""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Provide x-api-key header or ?key= query param.")
    if api_key != settings.WEBHOOK_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


@router.post("/trigger-call", response_model=TriggerCallResponse)
async def webhook_trigger_call(request: Request):
    """
    Public webhook for triggering calls from GHL or any external system.

    Auth: x-api-key header or ?key= query param must match WEBHOOK_API_KEY.

    Accepts two payload formats:

    1. Standard:
       { "phoneNumber": "+1...", "contactName": "John", "botConfigId": "uuid",
         "ghlContactId": "optional", "customVariableOverrides": {"key": "val"} }

    2. GHL customData (auto-detected):
       { "customData": { "phoneNumber": "...", "contactName": "...", "botConfigId": "...",
         "cvEventName": "...", "cvLocation": "..." }, "phone": "...", "full_name": "...",
         "contact_id": "..." }
       cv-prefixed keys in customData become variable overrides (cvEventName -> event_name).
    """
    _verify_api_key(request)

    body = await request.json()

    # --- Parse payload (GHL customData vs standard) ---
    phone_number: str | None = None
    contact_name: str | None = None
    bot_config_id: str | None = None
    ghl_contact_id: str | None = None
    custom_overrides: dict[str, str] = {}

    if body.get("customData") and isinstance(body["customData"], dict) and body["customData"].get("botConfigId"):
        # GHL webhook format
        cd = body["customData"]
        phone_number = cd.get("phoneNumber")
        contact_name = cd.get("contactName")
        bot_config_id = cd.get("botConfigId")
        ghl_contact_id = body.get("contact_id")

        # Extract cv* prefixed fields as variable overrides
        for key, value in cd.items():
            if key.startswith("cv") and len(key) > 2 and value:
                var_name = key[2:3].lower() + key[3:]
                custom_overrides[var_name] = str(value)

        # Fallback to top-level GHL contact fields
        if not phone_number:
            phone_number = body.get("phone")
        if not contact_name:
            contact_name = body.get("full_name") or " ".join(
                filter(None, [body.get("first_name"), body.get("last_name")])
            )

        logger.info("webhook_ghl_payload", phone=phone_number, bot_config=bot_config_id, ghl_contact=ghl_contact_id)
    else:
        # Standard format
        phone_number = body.get("phoneNumber")
        contact_name = body.get("contactName")
        bot_config_id = body.get("botConfigId")
        ghl_contact_id = body.get("ghlContactId")
        custom_overrides = body.get("customVariableOverrides") or {}

    # --- Validate ---
    if not phone_number:
        raise HTTPException(status_code=400, detail="phoneNumber is required.")
    if not bot_config_id:
        raise HTTPException(status_code=400, detail="botConfigId is required.")

    # --- Load bot config ---
    bot_config = await bot_config_loader.get(bot_config_id)
    if not bot_config:
        raise HTTPException(status_code=404, detail="Bot config not found.")

    contact_name = contact_name or "Customer"

    # --- Fill prompt template ---
    ctx_vars = bot_config.context_variables or {}
    template_vars = ctx_vars if isinstance(ctx_vars, dict) else {}
    template_vars.update(
        contact_name=contact_name,
        agent_name=bot_config.agent_name,
        company_name=bot_config.company_name,
        location=bot_config.location or "",
        event_name=bot_config.event_name or "",
        event_date=bot_config.event_date or "",
        event_time=bot_config.event_time or "",
    )
    template_vars.update(custom_overrides)

    filled_prompt = fill_prompt_template(bot_config.system_prompt_template, **template_vars)

    # --- Create call log ---
    call_sid = str(uuid4())

    async with get_db_session() as db:
        call_log = CallLog(
            bot_id=bot_config.id,
            call_sid=call_sid,
            contact_name=contact_name,
            contact_phone=phone_number,
            ghl_contact_id=ghl_contact_id,
            status="initiated",
            context_data={
                "bot_id": str(bot_config.id),
                "filled_prompt": filled_prompt,
                "contact_name": contact_name,
                "ghl_contact_id": ghl_contact_id,
                "ghl_webhook_url": bot_config.ghl_webhook_url,
                "tts_provider": bot_config.tts_provider,
                "tts_voice": bot_config.tts_voice,
                "tts_style_prompt": bot_config.tts_style_prompt,
                "language": bot_config.language,
                "silence_timeout_secs": bot_config.silence_timeout_secs,
            },
        )
        db.add(call_log)
        await db.flush()

        # --- Initiate outbound call ---
        provider = getattr(bot_config, "telephony_provider", "plivo") or "plivo"
        base_url = settings.PUBLIC_BASE_URL

        if provider == "twilio":
            provider_uuid = await twilio_make_call(
                account_sid=bot_config.twilio_account_sid,
                auth_token=bot_config.twilio_auth_token,
                from_number=bot_config.twilio_phone_number,
                to_number=phone_number,
                answer_url=f"{base_url}/twilio/answer/{call_sid}",
                status_callback_url=f"{base_url}/twilio/event/{call_sid}",
            )
        else:
            provider_uuid = await plivo_make_call(
                auth_id=bot_config.plivo_auth_id,
                auth_token=bot_config.plivo_auth_token,
                from_number=bot_config.plivo_caller_id,
                to_number=phone_number,
                answer_url=f"{base_url}/plivo/answer/{call_sid}",
                hangup_url=f"{base_url}/plivo/event/{call_sid}",
            )

        if not provider_uuid:
            call_log.status = "failed"
            await db.commit()
            raise HTTPException(status_code=502, detail=f"Failed to initiate {provider} call")

        call_log.plivo_call_uuid = provider_uuid
        call_log.status = "ringing"
        await db.commit()

    logger.info("webhook_call_triggered", call_sid=call_sid, provider=provider, to=phone_number, bot_id=bot_config_id)
    return TriggerCallResponse(call_sid=call_sid, status="ringing")
