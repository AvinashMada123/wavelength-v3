"""Call endpoints — trigger outbound calls and list call logs."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_config.loader import BotConfigLoader
from app.database import get_db
from app.models.call_log import CallLog
from app.models.call_queue import QueuedCall
from app.models.schemas import CallLogResponse, QueueEnqueueResponse, TriggerCallRequest
from sqlalchemy import select

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
    limit: int = 10000,
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


@router.post("/trigger", response_model=QueueEnqueueResponse, status_code=202)
async def trigger_call(req: TriggerCallRequest, db: AsyncSession = Depends(get_db)):
    """Enqueue a call for processing by the background queue processor."""
    # 1. Validate bot config exists
    bot_config = await bot_config_loader.get(str(req.bot_id))
    if not bot_config:
        raise HTTPException(status_code=404, detail="Bot config not found")

    # 2. Enqueue call
    queued_call = QueuedCall(
        bot_id=bot_config.id,
        contact_name=req.contact_name,
        contact_phone=req.contact_phone,
        ghl_contact_id=req.ghl_contact_id,
        extra_vars=req.extra_vars,
        source="api",
        status="queued",
    )
    db.add(queued_call)
    await db.commit()
    await db.refresh(queued_call)

    logger.info("call_enqueued", queue_id=str(queued_call.id), to=req.contact_phone, bot_id=str(req.bot_id))
    return QueueEnqueueResponse(queue_id=queued_call.id, status="queued")


@router.get("/{call_sid}/recording")
async def get_recording(call_sid: str, db: AsyncSession = Depends(get_db)):
    """Redirect to Plivo-hosted recording URL."""
    result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
    call_log = result.scalar_one_or_none()
    if not call_log:
        raise HTTPException(status_code=404, detail="Call not found")

    recording_url = (call_log.metadata_ or {}).get("recording_url")
    if not recording_url:
        raise HTTPException(status_code=404, detail="Recording not available")

    return RedirectResponse(url=recording_url)
