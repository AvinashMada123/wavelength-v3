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
from app.models.call_analytics import CallAnalytics
from app.models.call_queue import QueuedCall
from app.models.schemas import CallAnalyticsResponse, CallLogListResponse, CallLogResponse, QueueEnqueueResponse, TriggerCallRequest
from sqlalchemy import select

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/calls", tags=["calls"])

# Set during app startup
bot_config_loader: BotConfigLoader | None = None


def set_dependencies(loader: BotConfigLoader):
    global bot_config_loader
    bot_config_loader = loader


@router.get("", response_model=list[CallLogListResponse])
async def list_calls(
    bot_id: uuid.UUID | None = None,
    status: str | None = None,
    goal_outcome: str | None = None,
    limit: int = 10000,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    if goal_outcome:
        # Join with call_analytics to filter by goal_outcome
        query = (
            select(CallLog)
            .join(CallAnalytics, CallAnalytics.call_log_id == CallLog.id)
            .where(CallAnalytics.goal_outcome == goal_outcome)
            .order_by(CallLog.created_at.desc())
        )
    else:
        query = select(CallLog).order_by(CallLog.created_at.desc())
    if bot_id:
        query = query.where(CallLog.bot_id == bot_id)
    if status:
        query = query.where(CallLog.status == status)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/export", response_model=list[CallLogResponse])
async def export_calls(
    bot_id: uuid.UUID | None = None,
    goal_outcome: str | None = None,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
):
    """Full call logs with metadata (transcript + recording) for CSV export."""
    if goal_outcome:
        query = (
            select(CallLog)
            .join(CallAnalytics, CallAnalytics.call_log_id == CallLog.id)
            .where(CallAnalytics.goal_outcome == goal_outcome)
            .order_by(CallLog.created_at.desc())
        )
    else:
        query = select(CallLog).order_by(CallLog.created_at.desc())
    if bot_id:
        query = query.where(CallLog.bot_id == bot_id)
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{call_id}", response_model=CallLogResponse)
async def get_call(call_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallLog).where(CallLog.id == call_id))
    call_log = result.scalar_one_or_none()
    if not call_log:
        raise HTTPException(status_code=404, detail="Call not found")

    # Attach analytics if available
    analytics_result = await db.execute(
        select(CallAnalytics).where(CallAnalytics.call_log_id == call_id)
    )
    analytics_row = analytics_result.scalar_one_or_none()

    response = CallLogResponse.model_validate(call_log)
    if analytics_row:
        response.analytics = CallAnalyticsResponse(
            goal_outcome=analytics_row.goal_outcome,
            goal_type=analytics_row.goal_type,
            red_flags=analytics_row.red_flags,
            has_red_flags=analytics_row.has_red_flags,
            red_flag_max_severity=analytics_row.red_flag_max_severity,
            captured_data=analytics_row.captured_data,
            turn_count=analytics_row.turn_count,
            agent_word_share=analytics_row.agent_word_share,
        )
    return response


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
        extra_vars=req.merged_extra_vars(),
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
