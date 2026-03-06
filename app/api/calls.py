"""Call endpoints — trigger outbound calls and list call logs."""

from __future__ import annotations

import uuid
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_config.loader import BotConfigLoader, fill_prompt_template
from app.config import settings
from app.database import get_db
from app.models.call_log import CallLog
from app.models.schemas import CallLogResponse, TriggerCallRequest, TriggerCallResponse
from sqlalchemy import select
from app.plivo.client import make_outbound_call

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/calls", tags=["calls"])

# Set during app startup
bot_config_loader: BotConfigLoader | None = None


def set_dependencies(loader: BotConfigLoader):
    global bot_config_loader
    bot_config_loader = loader


@router.get("", response_model=list[CallLogResponse])
async def list_calls(
    bot_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(CallLog).order_by(CallLog.created_at.desc())
    if bot_id:
        query = query.where(CallLog.bot_id == bot_id)
    if status:
        query = query.where(CallLog.status == status)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/trigger", response_model=TriggerCallResponse)
async def trigger_call(req: TriggerCallRequest, db: AsyncSession = Depends(get_db)):
    # 1. Load bot config
    bot_config = await bot_config_loader.get(str(req.bot_id))
    if not bot_config:
        raise HTTPException(status_code=404, detail="Bot config not found")

    # 2. Fill system prompt template
    # Merge: context_variables defaults < extra_vars (overrides)
    template_vars = dict(bot_config.context_variables or {})
    template_vars.update(
        contact_name=req.contact_name,
        agent_name=bot_config.agent_name,
        company_name=bot_config.company_name,
        location=bot_config.location or "",
        event_name=bot_config.event_name or "",
        event_date=bot_config.event_date or "",
        event_time=bot_config.event_time or "",
    )
    template_vars.update(req.extra_vars)

    filled_prompt = fill_prompt_template(
        bot_config.system_prompt_template,
        **template_vars,
    )

    # 3. Create call_sid and call_log
    call_sid = str(uuid4())
    call_log = CallLog(
        bot_id=bot_config.id,
        call_sid=call_sid,
        contact_name=req.contact_name,
        contact_phone=req.contact_phone,
        ghl_contact_id=req.ghl_contact_id,
        status="initiated",
        context_data={
            "bot_id": str(bot_config.id),
            "filled_prompt": filled_prompt,
            "contact_name": req.contact_name,
            "ghl_contact_id": req.ghl_contact_id,
            "ghl_webhook_url": bot_config.ghl_webhook_url,
            "tts_voice": bot_config.tts_voice,
            "tts_style_prompt": bot_config.tts_style_prompt,
            "language": bot_config.language,
            "silence_timeout_secs": bot_config.silence_timeout_secs,
        },
    )
    db.add(call_log)
    await db.flush()

    # 4. Initiate Plivo outbound call (async wrapper around sync SDK)
    base_url = settings.PUBLIC_BASE_URL
    plivo_uuid = await make_outbound_call(
        auth_id=bot_config.plivo_auth_id,
        auth_token=bot_config.plivo_auth_token,
        from_number=bot_config.plivo_caller_id,
        to_number=req.contact_phone,
        answer_url=f"{base_url}/plivo/answer/{call_sid}",
        hangup_url=f"{base_url}/plivo/event/{call_sid}",
    )

    if not plivo_uuid:
        call_log.status = "failed"
        await db.commit()
        raise HTTPException(status_code=502, detail="Failed to initiate Plivo call")

    # 5. Update call_log with Plivo UUID
    call_log.plivo_call_uuid = plivo_uuid
    call_log.status = "ringing"
    await db.commit()

    logger.info("call_triggered", call_sid=call_sid, plivo_uuid=plivo_uuid, to=req.contact_phone)
    return TriggerCallResponse(call_sid=call_sid, status="ringing")
