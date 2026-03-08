"""Analytics API endpoints for goal-based call analysis and red flag monitoring."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.call_analytics import CallAnalytics
from app.models.call_log import CallLog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# --- Response schemas ---


class OutcomeSummary(BaseModel):
    outcome: str
    count: int
    percentage: float


class AnalyticsSummaryResponse(BaseModel):
    bot_id: uuid.UUID
    total_analyzed: int
    outcomes: list[OutcomeSummary]
    avg_duration_secs: float | None
    avg_agent_word_share: float | None
    red_flag_rate: float
    total_red_flags: int
    period_start: datetime | None
    period_end: datetime | None


class AnalyticsOutcomeItem(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID | None
    goal_outcome: str | None
    has_red_flags: bool
    red_flag_max_severity: str | None
    turn_count: int | None
    call_duration_secs: int | None
    agent_word_share: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RedFlagGroupItem(BaseModel):
    flag_id: str
    severity: str
    count: int
    calls: list[dict]


class AlertItem(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID | None
    bot_id: uuid.UUID
    goal_outcome: str | None
    red_flag_max_severity: str | None
    red_flags: list[dict] | None
    created_at: datetime
    contact_name: str | None = None
    contact_phone: str | None = None

    model_config = {"from_attributes": True}


class AlertsResponse(BaseModel):
    total_unacknowledged: int
    alerts: list[AlertItem]


class TrendPoint(BaseModel):
    date: str
    total: int
    outcomes: dict[str, int]
    red_flag_count: int


class CapturedDataFieldSummary(BaseModel):
    field_id: str
    values: list[dict]  # [{value: str, count: int}] for enums, [{value: str}] for strings
    total_captured: int


# --- Endpoints ---


@router.get("/{bot_id}/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    bot_id: uuid.UUID,
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Goal completion rates, outcome breakdown, avg duration, red flag rate."""
    query = select(CallAnalytics).where(CallAnalytics.bot_id == bot_id)
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)

    result = await db.execute(query)
    rows = result.scalars().all()

    if not rows:
        return AnalyticsSummaryResponse(
            bot_id=bot_id, total_analyzed=0, outcomes=[], avg_duration_secs=None,
            avg_agent_word_share=None, red_flag_rate=0.0, total_red_flags=0,
            period_start=start_date, period_end=end_date,
        )

    total = len(rows)
    outcome_counts: dict[str, int] = {}
    total_duration = 0
    duration_count = 0
    total_word_share = 0.0
    word_share_count = 0
    red_flag_count = sum(1 for r in rows if r.has_red_flags)

    for r in rows:
        outcome = r.goal_outcome or "unknown"
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        if r.call_duration_secs is not None:
            total_duration += r.call_duration_secs
            duration_count += 1
        if r.agent_word_share is not None:
            total_word_share += r.agent_word_share
            word_share_count += 1

    outcomes = [
        OutcomeSummary(
            outcome=k,
            count=v,
            percentage=round(v / total * 100, 1),
        )
        for k, v in sorted(outcome_counts.items(), key=lambda x: -x[1])
    ]

    return AnalyticsSummaryResponse(
        bot_id=bot_id,
        total_analyzed=total,
        outcomes=outcomes,
        avg_duration_secs=round(total_duration / duration_count, 1) if duration_count else None,
        avg_agent_word_share=round(total_word_share / word_share_count, 2) if word_share_count else None,
        red_flag_rate=round(red_flag_count / total * 100, 1),
        total_red_flags=red_flag_count,
        period_start=start_date,
        period_end=end_date,
    )


@router.get("/{bot_id}/outcomes", response_model=list[AnalyticsOutcomeItem])
async def get_analytics_outcomes(
    bot_id: uuid.UUID,
    outcome: str | None = Query(None),
    has_red_flags: bool | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of calls with goal outcomes."""
    query = select(CallAnalytics).where(CallAnalytics.bot_id == bot_id)
    if outcome:
        query = query.where(CallAnalytics.goal_outcome == outcome)
    if has_red_flags is not None:
        query = query.where(CallAnalytics.has_red_flags == has_red_flags)
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)

    query = query.order_by(CallAnalytics.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{bot_id}/red-flags")
async def get_analytics_red_flags(
    bot_id: uuid.UUID,
    severity: str | None = Query(None),
    flag_id: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Red flags grouped by severity with evidence quotes."""
    query = select(CallAnalytics).where(
        CallAnalytics.bot_id == bot_id,
        CallAnalytics.has_red_flags == True,
    )
    if severity:
        query = query.where(CallAnalytics.red_flag_max_severity == severity)
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)

    query = query.order_by(CallAnalytics.created_at.desc()).limit(500)
    result = await db.execute(query)
    rows = result.scalars().all()

    # Group by flag_id
    flag_groups: dict[str, dict] = {}
    for row in rows:
        if not row.red_flags:
            continue
        for rf in row.red_flags:
            rf_id = rf.get("id", "unknown")
            if flag_id and rf_id != flag_id:
                continue
            if rf_id not in flag_groups:
                flag_groups[rf_id] = {
                    "flag_id": rf_id,
                    "severity": rf.get("severity", "unknown"),
                    "count": 0,
                    "calls": [],
                }
            flag_groups[rf_id]["count"] += 1
            flag_groups[rf_id]["calls"].append({
                "analytics_id": str(row.id),
                "call_log_id": str(row.call_log_id) if row.call_log_id else None,
                "evidence": rf.get("evidence"),
                "created_at": row.created_at.isoformat(),
            })

    # Sort by severity priority
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    grouped = sorted(flag_groups.values(), key=lambda g: severity_order.get(g["severity"], 99))
    return grouped


@router.get("/{bot_id}/alerts", response_model=AlertsResponse)
async def get_analytics_alerts(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Unacknowledged critical/high red flags. Designed for GHL/n8n polling."""
    now = datetime.now(timezone.utc)

    query = (
        select(CallAnalytics)
        .where(
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.has_red_flags == True,
            CallAnalytics.acknowledged_at.is_(None),
            # Respect snooze: show if not snoozed or snooze has expired
            (CallAnalytics.snoozed_until.is_(None)) | (CallAnalytics.snoozed_until < now),
        )
        .order_by(CallAnalytics.created_at.desc())
        .limit(100)
    )

    result = await db.execute(query)
    analytics_rows = result.scalars().all()

    # Enrich with contact info from call_logs
    alerts = []
    call_log_ids = [r.call_log_id for r in analytics_rows if r.call_log_id]
    contact_map = {}
    if call_log_ids:
        cl_result = await db.execute(
            select(CallLog.id, CallLog.contact_name, CallLog.contact_phone)
            .where(CallLog.id.in_(call_log_ids))
        )
        for row in cl_result:
            contact_map[row.id] = {"name": row.contact_name, "phone": row.contact_phone}

    for row in analytics_rows:
        contact = contact_map.get(row.call_log_id, {})
        alerts.append(AlertItem(
            id=row.id,
            call_log_id=row.call_log_id,
            bot_id=row.bot_id,
            goal_outcome=row.goal_outcome,
            red_flag_max_severity=row.red_flag_max_severity,
            red_flags=row.red_flags,
            created_at=row.created_at,
            contact_name=contact.get("name"),
            contact_phone=contact.get("phone"),
        ))

    # Count total unacknowledged (may be more than the 100 returned)
    count_query = (
        select(func.count())
        .select_from(CallAnalytics)
        .where(
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.has_red_flags == True,
            CallAnalytics.acknowledged_at.is_(None),
            (CallAnalytics.snoozed_until.is_(None)) | (CallAnalytics.snoozed_until < now),
        )
    )
    total = (await db.execute(count_query)).scalar() or 0

    return AlertsResponse(total_unacknowledged=total, alerts=alerts)


@router.post("/{bot_id}/alerts/{analytics_id}/acknowledge")
async def acknowledge_alert(
    bot_id: uuid.UUID,
    analytics_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Mark a red flag alert as acknowledged."""
    result = await db.execute(
        select(CallAnalytics).where(
            CallAnalytics.id == analytics_id,
            CallAnalytics.bot_id == bot_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Analytics record not found")

    row.acknowledged_at = datetime.now(timezone.utc)
    row.acknowledged_by = body.get("acknowledged_by", "unknown")
    await db.commit()

    return {"status": "acknowledged", "id": str(analytics_id)}


@router.post("/{bot_id}/alerts/{analytics_id}/snooze")
async def snooze_alert(
    bot_id: uuid.UUID,
    analytics_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Snooze a red flag alert until a specified time."""
    snooze_until = body.get("snooze_until")
    if not snooze_until:
        raise HTTPException(status_code=422, detail="snooze_until is required")

    try:
        snooze_dt = datetime.fromisoformat(snooze_until)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="snooze_until must be ISO 8601 datetime")

    result = await db.execute(
        select(CallAnalytics).where(
            CallAnalytics.id == analytics_id,
            CallAnalytics.bot_id == bot_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Analytics record not found")

    row.snoozed_until = snooze_dt
    await db.commit()

    return {"status": "snoozed", "id": str(analytics_id), "snoozed_until": snooze_dt.isoformat()}


@router.get("/{bot_id}/trends", response_model=list[TrendPoint])
async def get_analytics_trends(
    bot_id: uuid.UUID,
    interval: str = Query("daily", pattern="^(daily|weekly)$"),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Time-series: daily/weekly goal completion rate and red flag rate."""
    if interval == "daily":
        date_trunc = func.date_trunc("day", CallAnalytics.created_at)
    else:
        date_trunc = func.date_trunc("week", CallAnalytics.created_at)

    query = (
        select(
            date_trunc.label("period"),
            CallAnalytics.goal_outcome,
            func.count().label("cnt"),
            func.sum(case((CallAnalytics.has_red_flags == True, 1), else_=0)).label("rf_cnt"),
        )
        .where(CallAnalytics.bot_id == bot_id)
        .group_by("period", CallAnalytics.goal_outcome)
        .order_by("period")
    )
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)

    result = await db.execute(query)
    rows = result.all()

    # Aggregate by period
    periods: dict[str, dict] = {}
    for row in rows:
        period_key = row.period.strftime("%Y-%m-%d")
        if period_key not in periods:
            periods[period_key] = {"date": period_key, "total": 0, "outcomes": {}, "red_flag_count": 0}
        periods[period_key]["total"] += row.cnt
        periods[period_key]["outcomes"][row.goal_outcome or "unknown"] = row.cnt
        periods[period_key]["red_flag_count"] += row.rf_cnt

    return [TrendPoint(**v) for v in periods.values()]


@router.get("/{bot_id}/captured-data", response_model=list[CapturedDataFieldSummary])
async def get_captured_data_summary(
    bot_id: uuid.UUID,
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated captured data per field. Enum fields: exact counts. String fields: raw values."""
    query = (
        select(CallAnalytics.captured_data)
        .where(
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.captured_data.isnot(None),
        )
    )
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)
    query = query.limit(1000)

    result = await db.execute(query)
    rows = [r[0] for r in result.all() if r[0]]

    if not rows:
        return []

    # Aggregate all field values
    field_values: dict[str, list] = {}
    for captured in rows:
        if not isinstance(captured, dict):
            continue
        for field_id, value in captured.items():
            if value is None:
                continue
            if field_id not in field_values:
                field_values[field_id] = []
            field_values[field_id].append(str(value))

    summaries = []
    for field_id, values in field_values.items():
        # Count unique values
        value_counts: dict[str, int] = {}
        for v in values:
            value_counts[v] = value_counts.get(v, 0) + 1

        sorted_values = sorted(value_counts.items(), key=lambda x: -x[1])
        summaries.append(CapturedDataFieldSummary(
            field_id=field_id,
            values=[{"value": v, "count": c} for v, c in sorted_values],
            total_captured=len(values),
        ))

    return summaries
