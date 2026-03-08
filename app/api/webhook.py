"""External webhook endpoint for triggering calls from GHL or other systems."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.bot_config.loader import BotConfigLoader
from app.database import get_db_session
from app.models.call_queue import QueuedCall
from app.models.schemas import QueueEnqueueResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# Set during app startup
bot_config_loader: BotConfigLoader | None = None


def set_dependencies(loader: BotConfigLoader):
    global bot_config_loader
    bot_config_loader = loader


def _verify_api_key(request: Request) -> None:
    """Verify x-api-key header or ?key= query param against WEBHOOK_API_KEY."""
    from app.config import settings

    if not settings.WEBHOOK_API_KEY:
        raise HTTPException(status_code=500, detail="WEBHOOK_API_KEY not configured on server")

    api_key = request.headers.get("x-api-key") or request.query_params.get("key") or ""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Provide x-api-key header or ?key= query param.")
    if api_key != settings.WEBHOOK_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


@router.post("/trigger-call", response_model=QueueEnqueueResponse, status_code=202)
async def webhook_trigger_call(request: Request):
    """
    Public webhook for triggering calls from GHL or any external system.

    Calls are now ENQUEUED rather than fired immediately. The background
    queue processor picks them up, checks the circuit breaker, and initiates
    the actual call.

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

    # --- Verify bot config exists ---
    bot_config = await bot_config_loader.get(bot_config_id)
    if not bot_config:
        raise HTTPException(status_code=404, detail="Bot config not found.")

    contact_name = contact_name or "Customer"

    # --- Enqueue call instead of firing immediately ---
    async with get_db_session() as db:
        queued_call = QueuedCall(
            bot_id=bot_config.id,
            contact_name=contact_name,
            contact_phone=phone_number,
            ghl_contact_id=ghl_contact_id,
            extra_vars=custom_overrides,
            source="webhook",
            status="queued",
        )
        db.add(queued_call)
        await db.commit()
        await db.refresh(queued_call)

    logger.info(
        "webhook_call_enqueued",
        queue_id=str(queued_call.id),
        phone=phone_number,
        bot_id=bot_config_id,
    )
    return QueueEnqueueResponse(queue_id=queued_call.id, status="queued")
