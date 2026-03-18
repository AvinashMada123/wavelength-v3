"""Sequence analytics API — overview, channels, failures, funnel, templates, leads, and lead detail endpoints."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db
from app.models.lead import Lead
from app.models.sequence import (
    SequenceInstance,
    SequenceStep,
    SequenceTemplate,
    SequenceTouchpoint,
)
from app.services.sequence_analytics import _cache_get, _cache_set, compute_engagement_score

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


class FunnelStep(BaseModel):
    step_order: int
    name: str
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    replied: int = 0
    drop_off_rate: float = 0.0


class FunnelResponse(BaseModel):
    template_name: str
    total_entered: int = 0
    steps: list[FunnelStep] = []


class TemplateStats(BaseModel):
    template_id: str
    name: str
    total_sent: int = 0
    completion_rate: float = 0.0
    reply_rate: float = 0.0
    avg_steps_completed: float = 0.0
    total_steps: int = 0
    active_instances: int = 0
    funnel_summary: list[int] = []


class TemplatesResponse(BaseModel):
    templates: list[TemplateStats] = []


class LeadStats(BaseModel):
    lead_id: str
    lead_name: str | None = None
    lead_phone: str | None = None
    score: int = 0
    tier: str = "inactive"
    active_sequences: int = 0
    total_replies: int = 0
    last_interaction_at: str | None = None


class TierSummary(BaseModel):
    hot: int = 0
    warm: int = 0
    cold: int = 0
    inactive: int = 0


class LeadsResponse(BaseModel):
    leads: list[LeadStats] = []
    tier_summary: TierSummary = TierSummary()
    total: int = 0
    page: int = 1
    page_size: int = 20


class ScoreDimension(BaseModel):
    score: int
    max: int


class ScoreBreakdown(BaseModel):
    activity: ScoreDimension
    recency: ScoreDimension
    outcome: ScoreDimension


class TimelineEntry(BaseModel):
    timestamp: str
    template_name: str
    step_name: str
    channel: str
    status: str
    content_preview: str | None = None
    reply_text: str | None = None


class LeadDetailResponse(BaseModel):
    lead_id: str
    lead_name: str | None = None
    score: int = 0
    tier: str = "inactive"
    score_breakdown: ScoreBreakdown
    active_sequences: int = 0
    total_replies: int = 0
    avg_reply_time_hours: float | None = None
    timeline: list[TimelineEntry] = []


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


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    template_id: uuid.UUID = Query(...),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
) -> FunnelResponse:
    """Funnel view for a specific template: per-step sent/skipped/failed/replied with drop-off."""
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "funnel", params)
    if cached is not None:
        return FunnelResponse(**cached)

    # Verify template exists and belongs to org
    tpl_q = select(SequenceTemplate).where(
        SequenceTemplate.id == template_id,
        SequenceTemplate.org_id == org_id,
    )
    tpl = (await db.execute(tpl_q)).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Get step names ordered by step_order
    steps_q = (
        select(SequenceStep.step_order, SequenceStep.name)
        .where(SequenceStep.template_id == template_id)
        .order_by(SequenceStep.step_order)
    )
    step_rows = (await db.execute(steps_q)).all()
    step_names: dict[int, str] = {row[0]: row[1] for row in step_rows}

    # Total entered = instance count for this template
    inst_count_q = (
        select(func.count())
        .select_from(SequenceInstance)
        .where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.template_id == template_id,
        )
    )
    total_entered = (await db.execute(inst_count_q)).scalar() or 0

    # Aggregate touchpoints by step_order
    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)
    tp_q = (
        select(
            SequenceTouchpoint.step_order,
            SequenceTouchpoint.status,
            func.count().label("cnt"),
        )
        .select_from(SequenceTouchpoint)
        .where(*filters, SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES))
        .group_by(SequenceTouchpoint.step_order, SequenceTouchpoint.status)
    )
    tp_rows = (await db.execute(tp_q)).all()

    # Build per-step aggregates
    step_data: dict[int, dict[str, int]] = {}
    for step_order, status, cnt in tp_rows:
        if step_order not in step_data:
            step_data[step_order] = {"sent": 0, "skipped": 0, "failed": 0, "replied": 0}
        if status in ("sent", "awaiting_reply", "replied"):
            step_data[step_order]["sent"] += cnt
        if status == "skipped":
            step_data[step_order]["skipped"] += cnt
        if status == "failed":
            step_data[step_order]["failed"] += cnt
        if status == "replied":
            step_data[step_order]["replied"] += cnt

    # Calculate drop-off rate relative to first step
    first_step_sent = 0
    sorted_orders = sorted(set(step_names.keys()) | set(step_data.keys()))
    if sorted_orders:
        first = sorted_orders[0]
        first_step_sent = step_data.get(first, {}).get("sent", 0)

    steps: list[FunnelStep] = []
    for order in sorted_orders:
        data = step_data.get(order, {"sent": 0, "skipped": 0, "failed": 0, "replied": 0})
        drop_off = max(0.0, round(1 - (data["sent"] / first_step_sent), 4)) if first_step_sent > 0 else 0.0
        steps.append(
            FunnelStep(
                step_order=order,
                name=step_names.get(order, f"Step {order}"),
                sent=data["sent"],
                skipped=data["skipped"],
                failed=data["failed"],
                replied=data["replied"],
                drop_off_rate=drop_off,
            )
        )

    result = FunnelResponse(
        template_name=tpl.name,
        total_entered=total_entered,
        steps=steps,
    )
    _cache_set(str(org_id), "funnel", params, result.model_dump())
    return result


@router.get("/templates", response_model=TemplatesResponse)
async def get_templates(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
) -> TemplatesResponse:
    """Per-template performance: sent, completion rate, reply rate, funnel summary."""
    params = _filter_params_dict(start_date, end_date, None, channel, bot_id)
    cached = _cache_get(str(org_id), "templates", params)
    if cached is not None:
        return TemplatesResponse(**cached)

    # Fetch all templates for the org
    tpl_q = (
        select(SequenceTemplate.id, SequenceTemplate.name)
        .where(SequenceTemplate.org_id == org_id)
        .order_by(SequenceTemplate.name)
    )
    tpl_rows = (await db.execute(tpl_q)).all()

    if not tpl_rows:
        result = TemplatesResponse(templates=[])
        _cache_set(str(org_id), "templates", params, result.model_dump())
        return result

    template_ids = [row[0] for row in tpl_rows]
    template_names: dict[uuid.UUID, str] = {row[0]: row[1] for row in tpl_rows}

    # Instance stats per template (exclude paused)
    inst_q = (
        select(
            SequenceInstance.template_id,
            SequenceInstance.status,
            func.count().label("cnt"),
        )
        .select_from(SequenceInstance)
        .where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.template_id.in_(template_ids),
            SequenceInstance.status.notin_(("paused",)),
        )
        .group_by(SequenceInstance.template_id, SequenceInstance.status)
    )
    inst_rows = (await db.execute(inst_q)).all()

    inst_data: dict[uuid.UUID, dict[str, int]] = {}
    for tid, status, cnt in inst_rows:
        if tid not in inst_data:
            inst_data[tid] = {}
        inst_data[tid][status] = cnt

    # Touchpoint stats per template: sent and replied counts (exclude pending/generating/scheduled)
    # Build base touchpoint filters without template_id (we group by it instead)
    base_tp_filters: list = [SequenceTouchpoint.org_id == org_id]
    if start_date:
        base_tp_filters.append(SequenceTouchpoint.scheduled_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        base_tp_filters.append(
            SequenceTouchpoint.scheduled_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )
    if channel:
        base_tp_filters.append(
            SequenceTouchpoint.step_id.in_(
                select(SequenceStep.id).where(SequenceStep.channel == channel)
            )
        )
    if bot_id:
        base_tp_filters.append(
            SequenceTouchpoint.instance_id.in_(
                select(SequenceInstance.id)
                .join(SequenceTemplate, SequenceTemplate.id == SequenceInstance.template_id)
                .where(SequenceTemplate.bot_id == bot_id)
            )
        )

    tp_status_q = (
        select(
            SequenceInstance.template_id,
            SequenceTouchpoint.status,
            func.count().label("cnt"),
        )
        .select_from(SequenceTouchpoint)
        .join(SequenceInstance, SequenceInstance.id == SequenceTouchpoint.instance_id)
        .where(
            *base_tp_filters,
            SequenceInstance.template_id.in_(template_ids),
            SequenceTouchpoint.status.notin_(_EXCLUDED_STATUSES),
        )
        .group_by(SequenceInstance.template_id, SequenceTouchpoint.status)
    )
    tp_rows = (await db.execute(tp_status_q)).all()

    tp_data: dict[uuid.UUID, dict[str, int]] = {}
    for tid, status, cnt in tp_rows:
        if tid not in tp_data:
            tp_data[tid] = {"sent": 0, "replied": 0}
        if status in ("sent", "awaiting_reply", "replied"):
            tp_data[tid]["sent"] += cnt
        if status == "replied":
            tp_data[tid]["replied"] += cnt

    # Step count per template
    step_count_q = (
        select(SequenceStep.template_id, func.count().label("cnt"))
        .select_from(SequenceStep)
        .where(SequenceStep.template_id.in_(template_ids))
        .group_by(SequenceStep.template_id)
    )
    step_count_rows = (await db.execute(step_count_q)).all()
    step_counts: dict[uuid.UUID, int] = {row[0]: row[1] for row in step_count_rows}

    # Funnel summary: sent counts per step_order per template
    funnel_q = (
        select(
            SequenceInstance.template_id,
            SequenceTouchpoint.step_order,
            func.count().label("cnt"),
        )
        .select_from(SequenceTouchpoint)
        .join(SequenceInstance, SequenceInstance.id == SequenceTouchpoint.instance_id)
        .where(
            *base_tp_filters,
            SequenceInstance.template_id.in_(template_ids),
            SequenceTouchpoint.status.in_(("sent", "awaiting_reply", "replied")),
        )
        .group_by(SequenceInstance.template_id, SequenceTouchpoint.step_order)
        .order_by(SequenceInstance.template_id, SequenceTouchpoint.step_order)
    )
    funnel_rows = (await db.execute(funnel_q)).all()

    funnel_data: dict[uuid.UUID, dict[int, int]] = {}
    for tid, step_order, cnt in funnel_rows:
        if tid not in funnel_data:
            funnel_data[tid] = {}
        funnel_data[tid][step_order] = cnt

    # Avg steps completed per instance per template (subquery approach)
    steps_per_instance = (
        select(
            SequenceInstance.template_id.label("template_id"),
            SequenceTouchpoint.instance_id.label("instance_id"),
            func.count().label("step_cnt"),
        )
        .select_from(SequenceTouchpoint)
        .join(SequenceInstance, SequenceInstance.id == SequenceTouchpoint.instance_id)
        .where(
            *base_tp_filters,
            SequenceInstance.template_id.in_(template_ids),
            SequenceTouchpoint.status.in_(("sent", "awaiting_reply", "replied")),
        )
        .group_by(SequenceInstance.template_id, SequenceTouchpoint.instance_id)
    ).subquery()

    avg_steps_q = (
        select(
            steps_per_instance.c.template_id,
            func.avg(steps_per_instance.c.step_cnt).label("avg_steps"),
        )
        .group_by(steps_per_instance.c.template_id)
    )
    avg_steps_rows = (await db.execute(avg_steps_q)).all()
    avg_steps: dict[uuid.UUID, float] = {row[0]: float(row[1]) for row in avg_steps_rows}

    # Build response
    templates: list[TemplateStats] = []
    for tid in template_ids:
        inst = inst_data.get(tid, {})
        total_inst = sum(inst.values())
        completed = inst.get("completed", 0)
        active = inst.get("active", 0)
        tp = tp_data.get(tid, {"sent": 0, "replied": 0})
        total_sent = tp["sent"]
        total_replied = tp["replied"]

        completion_rate = round(completed / total_inst, 4) if total_inst > 0 else 0.0
        reply_rate = round(total_replied / total_sent, 4) if total_sent > 0 else 0.0

        # Funnel summary: ordered list of sent counts per step
        fdata = funnel_data.get(tid, {})
        funnel_summary = [fdata[k] for k in sorted(fdata.keys())]

        templates.append(
            TemplateStats(
                template_id=str(tid),
                name=template_names[tid],
                total_sent=total_sent,
                completion_rate=completion_rate,
                reply_rate=reply_rate,
                avg_steps_completed=round(avg_steps.get(tid, 0.0), 2),
                total_steps=step_counts.get(tid, 0),
                active_instances=active,
                funnel_summary=funnel_summary,
            )
        )

    result = TemplatesResponse(templates=templates)
    _cache_set(str(org_id), "templates", params, result.model_dump())
    return result


@router.get("/leads", response_model=LeadsResponse)
async def get_leads(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    tier: str | None = Query(None, description="Filter by engagement tier: hot/warm/cold/inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("score"),
    sort_order: str = Query("desc"),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> LeadsResponse:
    """Leads engagement table with scoring, tier summary, and pagination."""
    # Cache key excludes pagination/sort — we cache the full scored list
    filter_params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cache_params = {**filter_params, "tier": tier}
    cache_key_params = {**filter_params}  # no tier/page/sort in cache key
    cached = _cache_get(str(org_id), "leads", cache_key_params)

    if cached is not None:
        scored_leads: list[dict] = cached["scored_leads"]
        tier_summary_data: dict = cached["tier_summary"]
    else:
        # --- 1. Get all unique lead_ids from touchpoints matching filters ---
        filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)
        lead_ids_q = (
            select(SequenceTouchpoint.lead_id)
            .select_from(SequenceTouchpoint)
            .where(*filters, SequenceTouchpoint.lead_id.isnot(None))
            .distinct()
        )
        lead_id_rows = (await db.execute(lead_ids_q)).all()
        lead_ids = [row[0] for row in lead_id_rows]

        if not lead_ids:
            return LeadsResponse()

        # --- 2. BATCH fetch: touchpoints, instances, lead info ---
        # All touchpoints for these leads (with filters applied)
        tp_q = (
            select(
                SequenceTouchpoint.lead_id,
                SequenceTouchpoint.status,
                SequenceTouchpoint.sent_at,
                SequenceTouchpoint.updated_at,
                SequenceTouchpoint.step_id,
            )
            .select_from(SequenceTouchpoint)
            .where(*filters, SequenceTouchpoint.lead_id.in_(lead_ids))
        )
        tp_rows = (await db.execute(tp_q)).all()

        # expects_reply lookup: batch fetch step_ids
        step_ids = {row.step_id for row in tp_rows if row.step_id is not None}
        expects_reply_map: dict[uuid.UUID, bool] = {}
        if step_ids:
            step_q = select(SequenceStep.id, SequenceStep.expects_reply).where(
                SequenceStep.id.in_(step_ids)
            )
            step_rows = (await db.execute(step_q)).all()
            expects_reply_map = {row[0]: row[1] for row in step_rows}

        # Group touchpoints by lead_id
        lead_touchpoints: dict[uuid.UUID, list[dict]] = defaultdict(list)
        for row in tp_rows:
            lead_touchpoints[row.lead_id].append({
                "status": row.status,
                "sent_at": row.sent_at,
                "updated_at": row.updated_at,
                "expects_reply": expects_reply_map.get(row.step_id, False),
            })

        # Instance counts per lead (completed and total)
        inst_q = (
            select(
                SequenceInstance.lead_id,
                SequenceInstance.status,
                func.count().label("cnt"),
            )
            .select_from(SequenceInstance)
            .where(
                SequenceInstance.org_id == org_id,
                SequenceInstance.lead_id.in_(lead_ids),
            )
            .group_by(SequenceInstance.lead_id, SequenceInstance.status)
        )
        inst_rows = (await db.execute(inst_q)).all()
        lead_instances: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in inst_rows:
            lead_instances[row.lead_id][row.status] = row.cnt

        # Lead info (batch)
        lead_info_q = select(Lead.id, Lead.contact_name, Lead.phone_number).where(
            Lead.id.in_(lead_ids)
        )
        lead_info_rows = (await db.execute(lead_info_q)).all()
        lead_info: dict[uuid.UUID, tuple[str | None, str | None]] = {
            row[0]: (row[1], row[2]) for row in lead_info_rows
        }

        # --- 3. Compute engagement score per lead ---
        scored_leads = []
        for lid in lead_ids:
            tps = lead_touchpoints.get(lid, [])
            inst = lead_instances.get(lid, {})
            completed_seqs = inst.get("completed", 0)
            total_seqs = sum(inst.values())
            active_seqs = inst.get("active", 0)

            eng = compute_engagement_score(tps, completed_seqs, total_seqs)

            total_replies = sum(1 for tp in tps if tp["status"] == "replied")

            # Last interaction: most recent updated_at or sent_at
            interaction_times = [
                tp["updated_at"] or tp["sent_at"]
                for tp in tps
                if tp["updated_at"] or tp["sent_at"]
            ]
            last_interaction = max(interaction_times).isoformat() if interaction_times else None

            name, phone = lead_info.get(lid, (None, None))

            scored_leads.append({
                "lead_id": str(lid),
                "lead_name": name,
                "lead_phone": phone,
                "score": eng["score"],
                "tier": eng["tier"],
                "active_sequences": active_seqs,
                "total_replies": total_replies,
                "last_interaction_at": last_interaction,
            })

        # --- 4. Tier summary (BEFORE tier filtering) ---
        tier_summary_data = {"hot": 0, "warm": 0, "cold": 0, "inactive": 0}
        for lead in scored_leads:
            t = lead["tier"]
            if t in tier_summary_data:
                tier_summary_data[t] += 1

        # Cache full scored list + tier summary
        _cache_set(str(org_id), "leads", cache_key_params, {
            "scored_leads": scored_leads,
            "tier_summary": tier_summary_data,
        })

    # --- 5. Apply tier filter AFTER computing summary ---
    filtered_leads = scored_leads
    if tier:
        filtered_leads = [l for l in scored_leads if l["tier"] == tier]

    # --- 6. Sort ---
    reverse = sort_order == "desc"
    if sort_by == "score":
        filtered_leads.sort(key=lambda l: l["score"], reverse=reverse)
    elif sort_by == "replies":
        filtered_leads.sort(key=lambda l: l["total_replies"], reverse=reverse)
    elif sort_by == "last_interaction":
        filtered_leads.sort(key=lambda l: l["last_interaction_at"] or "", reverse=reverse)
    else:
        filtered_leads.sort(key=lambda l: l["score"], reverse=reverse)

    # --- 7. Paginate ---
    total = len(filtered_leads)
    start = (page - 1) * page_size
    end = start + page_size
    page_leads = filtered_leads[start:end]

    return LeadsResponse(
        leads=[LeadStats(**l) for l in page_leads],
        tier_summary=TierSummary(**tier_summary_data),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead_detail(
    lead_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> LeadDetailResponse:
    """Single lead drill-down: engagement score breakdown, reply time, and timeline."""
    cache_params = {"lead_id": str(lead_id)}
    cached = _cache_get(str(org_id), "lead_detail", cache_params)
    if cached is not None:
        return LeadDetailResponse(**cached)

    # --- Verify lead has touchpoints in this org ---
    exists_q = (
        select(func.count())
        .select_from(SequenceTouchpoint)
        .where(
            SequenceTouchpoint.org_id == org_id,
            SequenceTouchpoint.lead_id == lead_id,
        )
    )
    tp_count = (await db.execute(exists_q)).scalar() or 0
    if tp_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found or has no touchpoints")

    # --- Lead info ---
    lead_q = select(Lead.contact_name, Lead.phone_number).where(Lead.id == lead_id)
    lead_row = (await db.execute(lead_q)).one_or_none()
    lead_name = lead_row[0] if lead_row else None

    # --- All touchpoints with step info (outerjoin SequenceStep) ---
    tp_q = (
        select(
            SequenceTouchpoint.id,
            SequenceTouchpoint.status,
            SequenceTouchpoint.sent_at,
            SequenceTouchpoint.updated_at,
            SequenceTouchpoint.created_at,
            SequenceTouchpoint.generated_content,
            SequenceTouchpoint.reply_text,
            SequenceTouchpoint.instance_id,
            SequenceTouchpoint.step_order,
            SequenceStep.name.label("step_name"),
            SequenceStep.channel.label("channel"),
            SequenceStep.expects_reply,
        )
        .select_from(SequenceTouchpoint)
        .outerjoin(SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id)
        .where(
            SequenceTouchpoint.org_id == org_id,
            SequenceTouchpoint.lead_id == lead_id,
        )
        .order_by(SequenceTouchpoint.created_at)
    )
    tp_rows = (await db.execute(tp_q)).all()

    # --- Instance data for this lead ---
    inst_q = (
        select(
            SequenceInstance.id,
            SequenceInstance.status,
            SequenceInstance.template_id,
        )
        .where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.lead_id == lead_id,
        )
    )
    inst_rows = (await db.execute(inst_q)).all()
    completed_seqs = sum(1 for r in inst_rows if r.status == "completed")
    total_seqs = len(inst_rows)
    active_seqs = sum(1 for r in inst_rows if r.status == "active")

    # --- Template names (batch) ---
    template_ids = {r.template_id for r in inst_rows}
    template_names: dict[uuid.UUID, str] = {}
    if template_ids:
        tpl_q = select(SequenceTemplate.id, SequenceTemplate.name).where(
            SequenceTemplate.id.in_(template_ids)
        )
        tpl_rows = (await db.execute(tpl_q)).all()
        template_names = {r[0]: r[1] for r in tpl_rows}

    # Instance -> template mapping
    inst_template: dict[uuid.UUID, uuid.UUID] = {r.id: r.template_id for r in inst_rows}

    # --- Compute engagement score ---
    touchpoint_dicts = [
        {
            "status": r.status,
            "sent_at": r.sent_at,
            "updated_at": r.updated_at,
            "expects_reply": r.expects_reply or False,
        }
        for r in tp_rows
    ]
    eng = compute_engagement_score(touchpoint_dicts, completed_seqs, total_seqs)

    total_replies = sum(1 for r in tp_rows if r.status == "replied")

    # --- Avg reply time ---
    reply_deltas = []
    for r in tp_rows:
        if r.status == "replied" and r.sent_at and r.updated_at:
            delta_seconds = (r.updated_at - r.sent_at).total_seconds()
            if delta_seconds > 0:
                reply_deltas.append(delta_seconds)
    avg_reply_time_hours = (
        round(sum(reply_deltas) / len(reply_deltas) / 3600, 2) if reply_deltas else None
    )

    # --- Build timeline ---
    timeline: list[TimelineEntry] = []
    for r in tp_rows:
        tpl_id = inst_template.get(r.instance_id)
        tpl_name = template_names.get(tpl_id, "Unknown") if tpl_id else "Unknown"
        content_preview = r.generated_content[:80] if r.generated_content else None

        timeline.append(TimelineEntry(
            timestamp=r.created_at.isoformat() if r.created_at else "",
            template_name=tpl_name,
            step_name=r.step_name or f"Step {r.step_order}",
            channel=r.channel or "unknown",
            status=r.status,
            content_preview=content_preview,
            reply_text=r.reply_text,
        ))

    breakdown = eng["breakdown"]
    result = LeadDetailResponse(
        lead_id=str(lead_id),
        lead_name=lead_name,
        score=eng["score"],
        tier=eng["tier"],
        score_breakdown=ScoreBreakdown(
            activity=ScoreDimension(**breakdown["activity"]),
            recency=ScoreDimension(**breakdown["recency"]),
            outcome=ScoreDimension(**breakdown["outcome"]),
        ),
        active_sequences=active_seqs,
        total_replies=total_replies,
        avg_reply_time_hours=avg_reply_time_hours,
        timeline=timeline,
    )

    _cache_set(str(org_id), "lead_detail", cache_params, result.model_dump())
    return result
