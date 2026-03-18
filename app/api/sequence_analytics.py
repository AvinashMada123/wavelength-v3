"""Sequence analytics API — overview, channels, and failures endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db
from app.models.sequence import (
    SequenceInstance,
    SequenceStep,
    SequenceTemplate,
    SequenceTouchpoint,
)
from app.services.sequence_analytics import _cache_get, _cache_set

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/sequences/analytics", tags=["sequence-analytics"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TrendData(BaseModel):
    sent_change: float | None = None
    reply_rate_change: float | None = None
    completion_rate_change: float | None = None
    avg_reply_time_change: float | None = None


class OverviewResponse(BaseModel):
    total_sent: int = 0
    total_failed: int = 0
    total_replied: int = 0
    reply_rate: float = 0.0
    completion_rate: float = 0.0
    avg_time_to_reply_hours: float | None = None
    trend: TrendData | None = None


class ChannelStats(BaseModel):
    channel: str
    sent: int = 0
    failed: int = 0
    replied: int = 0
    reply_rate: float = 0.0
    percentage_of_total: float = 0.0


class ChannelsResponse(BaseModel):
    channels: list[ChannelStats] = []


class FailureReason(BaseModel):
    reason: str
    count: int = 0
    percentage: float = 0.0


class RetryStats(BaseModel):
    total_retried: int = 0
    retry_success_count: int = 0
    retry_success_rate: float = 0.0


class FailuresResponse(BaseModel):
    total_failed: int = 0
    failure_reasons: list[FailureReason] = []
    retry_stats: RetryStats = RetryStats()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Touchpoint statuses to exclude from most counts (not yet actionable)
_EXCLUDED_STATUSES = ("pending", "generating", "scheduled")


def _build_touchpoint_filters(
    org_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    template_id: uuid.UUID | None,
    channel: str | None,
    bot_id: uuid.UUID | None,
) -> list:
    """Build WHERE clause conditions for touchpoint queries."""
    filters: list = [SequenceTouchpoint.org_id == org_id]

    if start_date:
        filters.append(SequenceTouchpoint.scheduled_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        filters.append(
            SequenceTouchpoint.scheduled_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )
    if template_id:
        filters.append(
            SequenceTouchpoint.instance_id.in_(
                select(SequenceInstance.id).where(SequenceInstance.template_id == template_id)
            )
        )
    if channel:
        filters.append(
            SequenceTouchpoint.step_id.in_(
                select(SequenceStep.id).where(SequenceStep.channel == channel)
            )
        )
    if bot_id:
        filters.append(
            SequenceTouchpoint.instance_id.in_(
                select(SequenceInstance.id)
                .join(SequenceTemplate, SequenceTemplate.id == SequenceInstance.template_id)
                .where(SequenceTemplate.bot_id == bot_id)
            )
        )

    return filters


def _filter_params_dict(
    start_date: date | None,
    end_date: date | None,
    template_id: uuid.UUID | None,
    channel: str | None,
    bot_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Convert filter params to a dict for cache key generation."""
    return {
        "start_date": str(start_date) if start_date else None,
        "end_date": str(end_date) if end_date else None,
        "template_id": str(template_id) if template_id else None,
        "channel": channel,
        "bot_id": str(bot_id) if bot_id else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
) -> OverviewResponse:
    """KPI overview: sent, failed, replied, rates, and trend vs. previous period."""
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "overview", params)
    if cached is not None:
        return OverviewResponse(**cached)

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # --- Status counts (exclude pending/generating/scheduled) ---
    status_q = (
        select(SequenceTouchpoint.status, func.count())
        .select_from(SequenceTouchpoint)
        .where(*filters, SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES))
        .group_by(SequenceTouchpoint.status)
    )
    rows = (await db.execute(status_q)).all()
    counts: dict[str, int] = {row[0]: row[1] for row in rows}

    total_sent = counts.get("sent", 0) + counts.get("awaiting_reply", 0) + counts.get("replied", 0)
    total_failed = counts.get("failed", 0)
    total_replied = counts.get("replied", 0)

    # --- Reply rate (only for steps with expects_reply=True) ---
    reply_base_filters = [
        *filters,
        SequenceTouchpoint.step_id.isnot(None),
        SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES),
    ]
    reply_total_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .join(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(*reply_base_filters, SequenceStep.expects_reply.is_(True))
    )
    reply_total = (await db.execute(reply_total_q)).scalar() or 0

    reply_count_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .join(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(
            *reply_base_filters,
            SequenceStep.expects_reply.is_(True),
            SequenceTouchpoint.status == "replied",
        )
    )
    reply_count = (await db.execute(reply_count_q)).scalar() or 0
    reply_rate = round(reply_count / reply_total, 4) if reply_total > 0 else 0.0

    # --- Completion rate (instances) ---
    inst_filters: list = [SequenceInstance.org_id == org_id]
    if template_id:
        inst_filters.append(SequenceInstance.template_id == template_id)
    if bot_id:
        inst_filters.append(
            SequenceInstance.template_id.in_(
                select(SequenceTemplate.id).where(SequenceTemplate.bot_id == bot_id)
            )
        )

    inst_q = (
        select(SequenceInstance.status, func.count())
        .select_from(SequenceInstance)
        .where(*inst_filters, SequenceInstance.status.notin_(("paused",)))
        .group_by(SequenceInstance.status)
    )
    inst_rows = (await db.execute(inst_q)).all()
    inst_counts: dict[str, int] = {r[0]: r[1] for r in inst_rows}
    completed = inst_counts.get("completed", 0)
    denom = completed + inst_counts.get("cancelled", 0) + inst_counts.get("active", 0)
    completion_rate = round(completed / denom, 4) if denom > 0 else 0.0

    # --- Avg time to reply ---
    avg_reply_q = (
        select(
            func.avg(
                func.extract("epoch", SequenceTouchpoint.updated_at)
                - func.extract("epoch", SequenceTouchpoint.sent_at)
            )
        )
        .select_from(SequenceTouchpoint)
        .where(*filters, SequenceTouchpoint.status == "replied", SequenceTouchpoint.sent_at.isnot(None))
    )
    avg_reply_seconds = (await db.execute(avg_reply_q)).scalar()
    avg_time_to_reply_hours = round(avg_reply_seconds / 3600, 2) if avg_reply_seconds else None

    # --- Trend (previous period comparison) ---
    trend = await _compute_trend(
        db, org_id, start_date, end_date, template_id, channel, bot_id,
        total_sent, reply_rate, completion_rate, avg_time_to_reply_hours,
    )

    result = OverviewResponse(
        total_sent=total_sent,
        total_failed=total_failed,
        total_replied=total_replied,
        reply_rate=reply_rate,
        completion_rate=completion_rate,
        avg_time_to_reply_hours=avg_time_to_reply_hours,
        trend=trend,
    )

    _cache_set(str(org_id), "overview", params, result.model_dump())
    return result


async def _compute_trend(
    db: AsyncSession,
    org_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    template_id: uuid.UUID | None,
    channel: str | None,
    bot_id: uuid.UUID | None,
    current_sent: int,
    current_reply_rate: float,
    current_completion_rate: float,
    current_avg_reply_hours: float | None,
) -> TrendData | None:
    """Compare current period to the equivalent previous period."""
    if not start_date or not end_date:
        return None

    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    prev_filters = _build_touchpoint_filters(org_id, prev_start, prev_end, template_id, channel, bot_id)

    # Check minimum data threshold
    count_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .where(*prev_filters, SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES))
    )
    prev_total = (await db.execute(count_q)).scalar() or 0
    if prev_total < 5:
        return None

    # Previous sent count
    prev_status_q = (
        select(SequenceTouchpoint.status, func.count())
        .select_from(SequenceTouchpoint)
        .where(*prev_filters, SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES))
        .group_by(SequenceTouchpoint.status)
    )
    prev_rows = (await db.execute(prev_status_q)).all()
    prev_counts: dict[str, int] = {r[0]: r[1] for r in prev_rows}
    prev_sent = prev_counts.get("sent", 0) + prev_counts.get("awaiting_reply", 0) + prev_counts.get("replied", 0)

    # Previous reply rate
    prev_reply_filters = [
        *prev_filters,
        SequenceTouchpoint.step_id.isnot(None),
        SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES),
    ]
    prev_reply_total_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .join(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(*prev_reply_filters, SequenceStep.expects_reply.is_(True))
    )
    prev_reply_total = (await db.execute(prev_reply_total_q)).scalar() or 0

    prev_reply_count_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .join(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(
            *prev_reply_filters,
            SequenceStep.expects_reply.is_(True),
            SequenceTouchpoint.status == "replied",
        )
    )
    prev_reply_count = (await db.execute(prev_reply_count_q)).scalar() or 0
    prev_reply_rate = round(prev_reply_count / prev_reply_total, 4) if prev_reply_total > 0 else 0.0

    # Previous completion rate
    prev_inst_filters: list = [SequenceInstance.org_id == org_id]
    if template_id:
        prev_inst_filters.append(SequenceInstance.template_id == template_id)
    if bot_id:
        prev_inst_filters.append(
            SequenceInstance.template_id.in_(
                select(SequenceTemplate.id).where(SequenceTemplate.bot_id == bot_id)
            )
        )
    # Note: completion rate is not time-bounded for simplicity (same as current period)
    prev_inst_q = (
        select(SequenceInstance.status, func.count())
        .select_from(SequenceInstance)
        .where(*prev_inst_filters, SequenceInstance.status.notin_(("paused",)))
        .group_by(SequenceInstance.status)
    )
    prev_inst_rows = (await db.execute(prev_inst_q)).all()
    prev_inst_counts: dict[str, int] = {r[0]: r[1] for r in prev_inst_rows}
    prev_completed = prev_inst_counts.get("completed", 0)
    prev_denom = prev_completed + prev_inst_counts.get("cancelled", 0) + prev_inst_counts.get("active", 0)
    prev_completion_rate = round(prev_completed / prev_denom, 4) if prev_denom > 0 else 0.0

    # Previous avg reply time
    prev_avg_q = (
        select(
            func.avg(
                func.extract("epoch", SequenceTouchpoint.updated_at)
                - func.extract("epoch", SequenceTouchpoint.sent_at)
            )
        )
        .select_from(SequenceTouchpoint)
        .where(*prev_filters, SequenceTouchpoint.status == "replied", SequenceTouchpoint.sent_at.isnot(None))
    )
    prev_avg_seconds = (await db.execute(prev_avg_q)).scalar()
    prev_avg_reply_hours = round(prev_avg_seconds / 3600, 2) if prev_avg_seconds else None

    # Compute changes
    sent_change = round((current_sent - prev_sent) / prev_sent * 100, 1) if prev_sent > 0 else None
    reply_rate_change = round((current_reply_rate - prev_reply_rate) * 100, 1) if prev_reply_total > 0 else None
    completion_rate_change = (
        round((current_completion_rate - prev_completion_rate) * 100, 1) if prev_denom > 0 else None
    )
    avg_reply_time_change = None
    if current_avg_reply_hours is not None and prev_avg_reply_hours is not None and prev_avg_reply_hours > 0:
        avg_reply_time_change = round(
            (current_avg_reply_hours - prev_avg_reply_hours) / prev_avg_reply_hours * 100, 1
        )

    return TrendData(
        sent_change=sent_change,
        reply_rate_change=reply_rate_change,
        completion_rate_change=completion_rate_change,
        avg_reply_time_change=avg_reply_time_change,
    )


@router.get("/channels", response_model=ChannelsResponse)
async def get_channels(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
) -> ChannelsResponse:
    """Per-channel breakdown: sent, failed, replied, reply_rate, percentage_of_total."""
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "channels", params)
    if cached is not None:
        return ChannelsResponse(**cached)

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    q = (
        select(
            SequenceStep.channel,
            SequenceTouchpoint.status,
            func.count().label("cnt"),
        )
        .select_from(SequenceTouchpoint)
        .join(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(*filters, SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES))
        .group_by(SequenceStep.channel, SequenceTouchpoint.status)
    )
    rows = (await db.execute(q)).all()

    # Aggregate per channel
    channel_data: dict[str, dict[str, int]] = {}
    for ch, status, cnt in rows:
        if ch not in channel_data:
            channel_data[ch] = {"sent": 0, "failed": 0, "replied": 0}
        if status in ("sent", "awaiting_reply", "replied"):
            channel_data[ch]["sent"] += cnt
        if status == "failed":
            channel_data[ch]["failed"] += cnt
        if status == "replied":
            channel_data[ch]["replied"] += cnt

    grand_total_sent = sum(d["sent"] for d in channel_data.values())

    channels: list[ChannelStats] = []
    for ch, data in sorted(channel_data.items()):
        sent = data["sent"]
        replied = data["replied"]
        channels.append(
            ChannelStats(
                channel=ch,
                sent=sent,
                failed=data["failed"],
                replied=replied,
                reply_rate=round(replied / sent, 4) if sent > 0 else 0.0,
                percentage_of_total=round(sent / grand_total_sent * 100, 1) if grand_total_sent > 0 else 0.0,
            )
        )

    result = ChannelsResponse(channels=channels)
    _cache_set(str(org_id), "channels", params, result.model_dump())
    return result


@router.get("/failures", response_model=FailuresResponse)
async def get_failures(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
) -> FailuresResponse:
    """Failure reasons grouped by error_message prefix, plus retry stats."""
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "failures", params)
    if cached is not None:
        return FailuresResponse(**cached)

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # Total failed
    total_failed_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .where(*filters, SequenceTouchpoint.status == "failed")
    )
    total_failed = (await db.execute(total_failed_q)).scalar() or 0

    # Failure reasons grouped by error_message prefix (first 50 chars)
    reasons_q = (
        select(
            func.left(SequenceTouchpoint.error_message, 50).label("reason"),
            func.count().label("cnt"),
        )
        .select_from(SequenceTouchpoint)
        .where(
            *filters,
            SequenceTouchpoint.status == "failed",
            SequenceTouchpoint.error_message.isnot(None),
        )
        .group_by(func.left(SequenceTouchpoint.error_message, 50))
        .order_by(func.count().desc())
    )
    reason_rows = (await db.execute(reasons_q)).all()

    failure_reasons = [
        FailureReason(
            reason=row.reason or "Unknown",
            count=row.cnt,
            percentage=round(row.cnt / total_failed * 100, 1) if total_failed > 0 else 0.0,
        )
        for row in reason_rows
    ]

    # Retry stats: touchpoints where retry_count > 0
    retried_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .where(*filters, SequenceTouchpoint.retry_count > 0)
    )
    total_retried = (await db.execute(retried_q)).scalar() or 0

    retry_success_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .where(
            *filters,
            SequenceTouchpoint.retry_count > 0,
            SequenceTouchpoint.status.in_(("sent", "awaiting_reply", "replied")),
        )
    )
    retry_success_count = (await db.execute(retry_success_q)).scalar() or 0

    retry_stats = RetryStats(
        total_retried=total_retried,
        retry_success_count=retry_success_count,
        retry_success_rate=round(retry_success_count / total_retried, 4) if total_retried > 0 else 0.0,
    )

    result = FailuresResponse(
        total_failed=total_failed,
        failure_reasons=failure_reasons,
        retry_stats=retry_stats,
    )
    _cache_set(str(org_id), "failures", params, result.model_dump())
    return result
