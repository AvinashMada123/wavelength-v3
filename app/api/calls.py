"""Call endpoints — trigger outbound calls and list call logs."""

from __future__ import annotations

import uuid

import structlog
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_org
from app.bot_config.loader import BotConfigLoader
from app.database import get_db
from app.services.billing import check_org_credits
from app.models.call_log import CallLog
from app.models.organization import Organization
from app.models.call_analytics import CallAnalytics
from app.models.call_queue import QueuedCall
from app.models.schemas import CallAnalyticsResponse, CallLogListAnalytics, CallLogListResponse, CallLogResponse, QueueEnqueueResponse, TriggerCallRequest
from app.utils import normalize_phone_india
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
    contact_phone: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10000,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    from datetime import datetime as dt

    # Always left-join analytics so we can return sentiment/score/interest
    query = (
        select(CallLog, CallAnalytics)
        .outerjoin(CallAnalytics, CallAnalytics.call_log_id == CallLog.id)
        .where(CallLog.org_id == org_id)
        .order_by(CallLog.created_at.desc())
    )
    if bot_id:
        query = query.where(CallLog.bot_id == bot_id)
    if status:
        query = query.where(CallLog.status == status)
    if goal_outcome:
        query = query.where(CallAnalytics.goal_outcome == goal_outcome)
    if contact_phone:
        query = query.where(CallLog.contact_phone == contact_phone)
    if date_from:
        try:
            query = query.where(CallLog.created_at >= dt.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.where(CallLog.created_at <= dt.fromisoformat(date_to))
        except ValueError:
            pass
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    # Build response with analytics attached
    response = []
    for call_log, analytics in rows:
        data = CallLogListResponse.model_validate(call_log)
        data.metadata = call_log.metadata_
        if analytics:
            data.analytics = CallLogListAnalytics(
                goal_outcome=analytics.goal_outcome,
                sentiment=analytics.sentiment,
                sentiment_score=analytics.sentiment_score,
                lead_temperature=analytics.lead_temperature,
                captured_data=analytics.captured_data,
                has_red_flags=analytics.has_red_flags,
            )
        response.append(data)
    return response


@router.get("/export", response_model=list[CallLogResponse])
async def export_calls(
    bot_id: uuid.UUID | None = None,
    goal_outcome: str | None = None,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Full call logs with metadata (transcript + recording) for CSV export."""
    if goal_outcome:
        query = (
            select(CallLog)
            .join(CallAnalytics, CallAnalytics.call_log_id == CallLog.id)
            .where(CallAnalytics.goal_outcome == goal_outcome, CallLog.org_id == org_id)
            .order_by(CallLog.created_at.desc())
        )
    else:
        query = select(CallLog).where(CallLog.org_id == org_id).order_by(CallLog.created_at.desc())
    if bot_id:
        query = query.where(CallLog.bot_id == bot_id)
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{call_id}", response_model=CallLogResponse)
async def get_call(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    result = await db.execute(select(CallLog).where(CallLog.id == call_id, CallLog.org_id == org_id))
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
async def trigger_call(
    req: TriggerCallRequest,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Enqueue a call for processing by the background queue processor."""
    # 1. Validate bot config exists and belongs to the user's org
    bot_config = await bot_config_loader.get(str(req.bot_id))
    if not bot_config or bot_config.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bot config not found")

    # 2. Check credits before enqueuing
    has_credits, balance = await check_org_credits(db, org_id)
    if not has_credits:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits. Current balance: {float(balance):.2f}. Please recharge to continue making calls.",
        )

    # 3. Normalize phone & enqueue call
    normalized_phone = normalize_phone_india(req.contact_phone)
    queued_call = QueuedCall(
        org_id=org_id,
        bot_id=bot_config.id,
        contact_name=req.contact_name,
        contact_phone=normalized_phone,
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
async def get_recording(
    call_sid: str,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Redirect to Plivo-hosted recording URL.

    Accepts ?token= query param for auth since <audio> elements can't send headers.
    """
    from app.auth.security import decode_token as _decode
    from app.models.user import User

    if not token:
        raise HTTPException(status_code=401, detail="Missing token query parameter")

    try:
        payload = _decode(token)
        if payload.get("type") != "access" or not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token")
        result = await db.execute(select(User).where(User.id == uuid.UUID(payload["sub"])))
        user = result.scalar_one_or_none()
        if not user or user.status != "active":
            raise HTTPException(status_code=401, detail="Invalid token")
        org_id = user.org_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid, CallLog.org_id == org_id))
    call_log = result.scalar_one_or_none()
    if not call_log:
        raise HTTPException(status_code=404, detail="Call not found")

    recording_url = (call_log.metadata_ or {}).get("recording_url")
    if not recording_url:
        raise HTTPException(status_code=404, detail="Recording not available")

    # Twilio recording URLs require HTTP Basic Auth — proxy them server-side
    if "api.twilio.com" in recording_url or "twilio.com" in recording_url:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()
        if not org or not org.twilio_account_sid or not org.twilio_auth_token:
            raise HTTPException(status_code=500, detail="Twilio credentials not configured")

        twilio_auth = (org.twilio_account_sid, org.twilio_auth_token)

        # Fetch entire recording and return it (avoids Content-Length mismatch with streaming)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(recording_url, auth=twilio_auth)
            resp.raise_for_status()

        content_type = "audio/mpeg" if recording_url.endswith(".mp3") else "audio/wav"
        return Response(
            content=resp.content,
            media_type=content_type,
            headers={"content-length": str(len(resp.content))},
        )

    return RedirectResponse(url=recording_url)
