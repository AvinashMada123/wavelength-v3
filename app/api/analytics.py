"""Analytics API endpoints for goal-based call analysis, red flag monitoring,
dashboard aggregation, and cost breakdown."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, extract, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from app.auth.dependencies import get_current_user, get_current_org
from app.database import get_db
from app.models.billing import CreditTransaction
from app.models.bot_config import BotConfig
from app.models.call_analytics import CallAnalytics
from app.models.call_log import CallLog
from app.services.call_analyzer import CallAnalyzer

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


# --- Dashboard / cost response schemas ---


class CallVolumePoint(BaseModel):
    date: str
    total: int
    connected: int


class HeatmapCell(BaseModel):
    hour: int  # 0-23
    day_of_week: int  # 0=Monday .. 6=Sunday
    count: int


class ConversionFunnelStep(BaseModel):
    stage: str
    count: int
    percentage: float


class DashboardResponse(BaseModel):
    total_calls: int
    connected_pct: float
    avg_duration_secs: float | None
    conversion_pct: float
    total_cost: float
    cost_per_conversion: float | None
    call_volume_by_day: list[CallVolumePoint]
    outcome_distribution: dict[str, int]
    sentiment_distribution: dict[str, int]
    top_objections: list[dict]
    calling_heatmap: list[HeatmapCell]
    conversion_funnel: list[ConversionFunnelStep]


class CostByType(BaseModel):
    telephony: float
    llm: float
    tts: float
    stt: float


class DailyCost(BaseModel):
    date: str
    cost: float


class CostBreakdownResponse(BaseModel):
    total_cost: float
    cost_per_call: float | None
    cost_per_conversion: float | None
    cost_by_type: CostByType
    daily_costs: list[DailyCost]


# --- Endpoints ---
# NOTE: Static path endpoints (/dashboard, /cost-breakdown) MUST be defined
# before parameterized /{bot_id}/... routes to avoid FastAPI treating the
# path segment as a UUID parameter.


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    bot_id: uuid.UUID | None = Query(None, description="Filter by bot ID"),
    days: int = Query(30, ge=1, le=90, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Aggregated dashboard data: volume, outcomes, sentiment, heatmap, funnel."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Base filters for call_logs
    cl_filters = [CallLog.org_id == org_id, CallLog.created_at >= since]
    if bot_id:
        cl_filters.append(CallLog.bot_id == bot_id)

    # --- Total calls & connected % & avg duration ---
    stats_query = select(
        func.count().label("total"),
        func.sum(case((and_(CallLog.status == "completed", CallLog.call_duration > 10), 1), else_=0)).label("connected"),
        func.avg(CallLog.call_duration).label("avg_duration"),
    ).where(*cl_filters)
    stats_row = (await db.execute(stats_query)).one()
    total_calls = stats_row.total or 0
    connected = stats_row.connected or 0
    connected_pct = round(connected / total_calls * 100, 1) if total_calls else 0.0
    avg_duration = round(float(stats_row.avg_duration), 1) if stats_row.avg_duration else None

    # --- Analytics-based metrics (outcomes, sentiment) ---
    ca_filters = [CallAnalytics.org_id == org_id, CallAnalytics.created_at >= since]
    if bot_id:
        ca_filters.append(CallAnalytics.bot_id == bot_id)

    analytics_query = select(
        CallAnalytics.goal_outcome,
        CallAnalytics.red_flags,
        CallAnalytics.captured_data,
    ).where(*ca_filters)
    analytics_result = await db.execute(analytics_query)
    analytics_rows = analytics_result.all()

    # Outcome distribution
    outcome_dist: dict[str, int] = {}
    sentiment_dist: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
    objection_counts: dict[str, int] = {}
    conversions = 0

    # Load primary success criteria IDs from bot's goal_config (if bot_id specified)
    primary_criteria_ids: set[str] | None = None
    if bot_id:
        bot_result = await db.execute(
            select(BotConfig.goal_config).where(BotConfig.id == bot_id, BotConfig.org_id == org_id)
        )
        goal_cfg_raw = bot_result.scalar_one_or_none()
        if goal_cfg_raw and isinstance(goal_cfg_raw, dict):
            criteria = goal_cfg_raw.get("success_criteria", [])
            primaries = {c["id"] for c in criteria if isinstance(c, dict) and c.get("is_primary")}
            if primaries:
                primary_criteria_ids = primaries

    for row in analytics_rows:
        outcome = row.goal_outcome or "unknown"
        outcome_dist[outcome] = outcome_dist.get(outcome, 0) + 1
        # Count conversions: if primary criteria defined, only those count;
        # otherwise fall back to any outcome that isn't "none"/"unknown"
        if primary_criteria_ids is not None:
            if outcome in primary_criteria_ids:
                conversions += 1
        elif outcome not in ("none", "unknown"):
            conversions += 1

        # Extract sentiment from captured_data if available
        captured = row.captured_data or {}
        sentiment_val = captured.get("sentiment")
        if sentiment_val in sentiment_dist:
            sentiment_dist[sentiment_val] += 1

        # Extract objections from red_flags or captured_data
        flags = row.red_flags or []
        if isinstance(flags, list):
            for flag in flags:
                if isinstance(flag, dict):
                    flag_id = flag.get("id", "unknown")
                    objection_counts[flag_id] = objection_counts.get(flag_id, 0) + 1

    conversion_pct = round(conversions / total_calls * 100, 1) if total_calls else 0.0

    # --- Total cost (from credit transactions) ---
    cost_query = select(
        func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)
    ).where(
        CreditTransaction.org_id == org_id,
        CreditTransaction.type == "usage",
        CreditTransaction.created_at >= since,
    )
    total_cost = float((await db.execute(cost_query)).scalar_one())
    cost_per_conversion = round(total_cost / conversions, 2) if conversions else None

    # --- Call volume by day ---
    volume_query = (
        select(
            func.date_trunc("day", CallLog.created_at).label("day"),
            func.count().label("total"),
            func.sum(case((and_(CallLog.status == "completed", CallLog.call_duration > 10), 1), else_=0)).label("connected"),
        )
        .where(*cl_filters)
        .group_by("day")
        .order_by("day")
    )
    volume_result = await db.execute(volume_query)
    call_volume = [
        CallVolumePoint(
            date=row.day.strftime("%Y-%m-%d"),
            total=row.total,
            connected=row.connected,
        )
        for row in volume_result.all()
    ]

    # --- Calling heatmap (hour x day_of_week) ---
    # TODO: Timezone should be org-configurable. Hardcoded to IST for now (all users are Indian).
    ist_created_at = func.timezone('Asia/Kolkata', CallLog.created_at)
    heatmap_query = (
        select(
            extract("hour", ist_created_at).label("hour"),
            extract("dow", ist_created_at).label("dow"),  # 0=Sunday in PG
            func.count().label("cnt"),
        )
        .where(*cl_filters)
        .group_by("hour", "dow")
    )
    heatmap_result = await db.execute(heatmap_query)
    heatmap = []
    for row in heatmap_result.all():
        # Convert PG dow (0=Sunday) to ISO (0=Monday)
        pg_dow = int(row.dow)
        iso_dow = (pg_dow - 1) % 7  # Sunday(0)->6, Monday(1)->0, etc.
        heatmap.append(HeatmapCell(hour=int(row.hour), day_of_week=iso_dow, count=row.cnt))

    # --- Top objections (sorted by frequency) ---
    top_objections = sorted(
        [{"flag_id": k, "count": v} for k, v in objection_counts.items()],
        key=lambda x: -x["count"],
    )[:10]

    # --- Conversion funnel ---
    funnel = [
        ConversionFunnelStep(stage="Initiated", count=total_calls, percentage=100.0),
        ConversionFunnelStep(
            stage="Connected",
            count=connected,
            percentage=round(connected / total_calls * 100, 1) if total_calls else 0.0,
        ),
        ConversionFunnelStep(
            stage="Analyzed",
            count=len(analytics_rows),
            percentage=round(len(analytics_rows) / total_calls * 100, 1) if total_calls else 0.0,
        ),
        ConversionFunnelStep(
            stage="Converted",
            count=conversions,
            percentage=conversion_pct,
        ),
    ]

    return DashboardResponse(
        total_calls=total_calls,
        connected_pct=connected_pct,
        avg_duration_secs=avg_duration,
        conversion_pct=conversion_pct,
        total_cost=total_cost,
        cost_per_conversion=cost_per_conversion,
        call_volume_by_day=call_volume,
        outcome_distribution=outcome_dist,
        sentiment_distribution=sentiment_dist,
        top_objections=top_objections,
        calling_heatmap=heatmap,
        conversion_funnel=funnel,
    )


@router.get("/cost-breakdown", response_model=CostBreakdownResponse)
async def get_cost_breakdown(
    bot_id: uuid.UUID | None = Query(None, description="Filter by bot ID"),
    days: int = Query(30, ge=1, le=90, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Cost breakdown: total, per-call, per-conversion, by type, and daily trend."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Connected calls only (for per-call cost — only completed calls are billed)
    cl_filters = [
        CallLog.org_id == org_id,
        CallLog.created_at >= since,
        CallLog.status == "completed",
    ]
    if bot_id:
        cl_filters.append(CallLog.bot_id == bot_id)

    connected_calls = (await db.execute(
        select(func.count()).select_from(CallLog).where(*cl_filters)
    )).scalar_one()

    # Conversions (for per-conversion cost)
    ca_filters = [CallAnalytics.org_id == org_id, CallAnalytics.created_at >= since]
    if bot_id:
        ca_filters.append(CallAnalytics.bot_id == bot_id)

    conversion_query = select(func.count()).select_from(CallAnalytics).where(
        *ca_filters,
        CallAnalytics.goal_outcome.isnot(None),
        CallAnalytics.goal_outcome != "none",
    )
    conversions = (await db.execute(conversion_query)).scalar_one()

    # Total cost from usage transactions
    cost_query = select(
        func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)
    ).where(
        CreditTransaction.org_id == org_id,
        CreditTransaction.type == "usage",
        CreditTransaction.created_at >= since,
    )
    total_cost = float((await db.execute(cost_query)).scalar_one())

    cost_per_call = round(total_cost / connected_calls, 2) if connected_calls else None
    cost_per_conversion = round(total_cost / conversions, 2) if conversions else None

    # Cost by type -- estimated split based on typical AI calling cost distribution.
    # Telephony ~40%, LLM ~30%, TTS ~20%, STT ~10% of total credit cost.
    cost_by_type = CostByType(
        telephony=round(total_cost * 0.40, 2),
        llm=round(total_cost * 0.30, 2),
        tts=round(total_cost * 0.20, 2),
        stt=round(total_cost * 0.10, 2),
    )

    # Daily cost trend
    daily_query = (
        select(
            func.date_trunc("day", CreditTransaction.created_at).label("day"),
            func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0).label("cost"),
        )
        .where(
            CreditTransaction.org_id == org_id,
            CreditTransaction.type == "usage",
            CreditTransaction.created_at >= since,
        )
        .group_by("day")
        .order_by("day")
    )
    daily_result = await db.execute(daily_query)
    daily_costs = [
        DailyCost(date=row.day.strftime("%Y-%m-%d"), cost=round(float(row.cost), 2))
        for row in daily_result.all()
    ]

    return CostBreakdownResponse(
        total_cost=total_cost,
        cost_per_call=cost_per_call,
        cost_per_conversion=cost_per_conversion,
        cost_by_type=cost_by_type,
        daily_costs=daily_costs,
    )


# --- Lead Intelligence endpoint ---


class LeadIntelResponse(BaseModel):
    temperature_distribution: dict[str, int]
    buying_signals: list[dict]  # [{signal: str, count: int}]
    total_analyzed: int


@router.get("/lead-intelligence", response_model=LeadIntelResponse)
async def get_lead_intelligence(
    bot_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Lead temperature distribution and buying signals frequency."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    filters = [CallAnalytics.org_id == org_id, CallAnalytics.created_at >= since]
    if bot_id:
        filters.append(CallAnalytics.bot_id == bot_id)

    rows = (await db.execute(
        select(CallAnalytics.lead_temperature, CallAnalytics.buying_signals)
        .where(*filters)
        .where(CallAnalytics.lead_temperature.isnot(None))
    )).all()

    temp_dist: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    for row in rows:
        t = row.lead_temperature or "unknown"
        temp_dist[t] = temp_dist.get(t, 0) + 1
        if row.buying_signals:
            for sig in row.buying_signals:
                if isinstance(sig, str) and sig.strip():
                    signal_counts[sig.strip()] = signal_counts.get(sig.strip(), 0) + 1

    top_signals = sorted(
        [{"signal": k, "count": v} for k, v in signal_counts.items()],
        key=lambda x: -x["count"],
    )[:15]

    return LeadIntelResponse(
        temperature_distribution=temp_dist,
        buying_signals=top_signals,
        total_analyzed=len(rows),
    )


# --- Reanalysis endpoint ---


class ReanalysisResponse(BaseModel):
    total_eligible: int
    processed: int
    succeeded: int
    failed: int
    errors: list[str]


def _compute_agent_word_share(transcript: list[dict]) -> float:
    bot_words = sum(len(t["content"].split()) for t in transcript if t.get("role") == "assistant")
    user_words = sum(len(t["content"].split()) for t in transcript if t.get("role") == "user")
    total = bot_words + user_words
    return round(bot_words / total, 2) if total > 0 else 0.0


def _get_max_severity(red_flags: list) -> str | None:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    if not red_flags:
        return None
    severities = [rf.get("severity", "low") for rf in red_flags]
    return min(severities, key=lambda s: severity_order.get(s, 99))


@router.post("/reanalyze", response_model=ReanalysisResponse)
async def reanalyze_calls(
    bot_id: uuid.UUID | None = Query(None, description="Only reanalyze calls for this bot"),
    limit: int = Query(100, ge=1, le=500, description="Max calls to reanalyze"),
    force: bool = Query(False, description="Re-run even if CallAnalytics row exists"),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Reanalyze historical calls that have transcripts.

    Finds calls with transcript data and runs the enhanced CallAnalyzer
    to populate/update CallAnalytics rows with sentiment, temperature,
    objections, buying signals, etc.
    """
    # Find eligible calls: have metadata with transcript
    filters = [
        CallLog.org_id == org_id,
        CallLog.status == "completed",
        CallLog.metadata_.isnot(None),
    ]
    if bot_id:
        filters.append(CallLog.bot_id == bot_id)

    if not force:
        # Only calls WITHOUT existing CallAnalytics row
        subq = select(CallAnalytics.call_log_id).where(
            CallAnalytics.call_log_id.isnot(None)
        ).correlate(CallLog)
        filters.append(~CallLog.id.in_(subq))

    query = (
        select(CallLog)
        .where(*filters)
        .order_by(CallLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    calls = result.scalars().all()

    total_eligible = len(calls)
    if total_eligible == 0:
        return ReanalysisResponse(
            total_eligible=0, processed=0, succeeded=0, failed=0, errors=[]
        )

    # Load bot configs for goal_config
    bot_ids = list({c.bot_id for c in calls})
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id.in_(bot_ids))
    )
    bots_by_id = {b.id: b for b in bot_result.scalars().all()}

    analyzer = CallAnalyzer()
    succeeded = 0
    failed = 0
    errors: list[str] = []

    for call in calls:
        try:
            meta = call.metadata_ or {}
            transcript = meta.get("transcript", [])
            if not transcript or len(transcript) < 2:
                continue

            bot_cfg = bots_by_id.get(call.bot_id)
            goal_cfg = None
            system_prompt = ""
            if bot_cfg:
                goal_cfg = bot_cfg.goal_config
                system_prompt = bot_cfg.system_prompt_template or ""

            analysis = await analyzer.analyze(
                transcript=transcript,
                goal_config=goal_cfg,
                system_prompt=system_prompt,
                realtime_red_flags=[],
                call_sid=call.call_sid,
            )

            if not analysis:
                failed += 1
                errors.append(f"{call.call_sid}: analysis returned None")
                continue

            # Build analytics data
            red_flags_dicts = [rf.model_dump() for rf in analysis.red_flags]
            has_flags = len(red_flags_dicts) > 0
            max_severity = _get_max_severity(red_flags_dicts) if has_flags else None

            goal_type = None
            if goal_cfg:
                goal_type = goal_cfg.get("goal_type") if isinstance(goal_cfg, dict) else getattr(goal_cfg, "goal_type", None)

            analytics_data = dict(
                org_id=call.org_id,
                bot_id=call.bot_id,
                goal_type=goal_type,
                goal_outcome=analysis.goal_outcome,
                has_red_flags=has_flags,
                red_flag_max_severity=max_severity,
                red_flags=red_flags_dicts if has_flags else None,
                captured_data=analysis.captured_data or None,
                sentiment=analysis.sentiment,
                sentiment_score=analysis.sentiment_score,
                lead_temperature=analysis.lead_temperature,
                objections=analysis.objections,
                buying_signals=analysis.buying_signals,
                turn_count=len([t for t in transcript if t.get("role") == "user"]),
                call_duration_secs=call.call_duration,
                agent_word_share=_compute_agent_word_share(transcript),
                analysis_input_tokens=analysis.input_tokens,
                analysis_output_tokens=analysis.output_tokens,
            )

            # Upsert
            existing = await db.execute(
                select(CallAnalytics).where(CallAnalytics.call_log_id == call.id)
            )
            existing_row = existing.scalar_one_or_none()

            if existing_row:
                for key, value in analytics_data.items():
                    setattr(existing_row, key, value)
            else:
                row = CallAnalytics(call_log_id=call.id, **analytics_data)
                db.add(row)

            # Update call metadata with new analysis fields
            updated_meta = dict(meta)
            if analysis.summary:
                updated_meta["interest_level"] = analysis.interest_level
            if analysis.sentiment:
                updated_meta["sentiment"] = analysis.sentiment
                updated_meta["sentiment_score"] = analysis.sentiment_score
            if analysis.lead_temperature:
                updated_meta["lead_temperature"] = analysis.lead_temperature
            if analysis.goal_outcome:
                updated_meta["goal_outcome"] = analysis.goal_outcome
            call.metadata_ = updated_meta

            if analysis.summary and not call.summary:
                call.summary = analysis.summary

            await db.commit()
            succeeded += 1

            logger.info(
                "reanalysis_completed",
                call_sid=call.call_sid,
                sentiment=analysis.sentiment,
                temperature=analysis.lead_temperature,
                goal_outcome=analysis.goal_outcome,
            )

        except Exception as e:
            failed += 1
            errors.append(f"{call.call_sid}: {str(e)[:100]}")
            logger.error("reanalysis_failed", call_sid=call.call_sid, error=str(e))
            await db.rollback()

    return ReanalysisResponse(
        total_eligible=total_eligible,
        processed=succeeded + failed,
        succeeded=succeeded,
        failed=failed,
        errors=errors[:20],  # cap error messages
    )


# --- Bot-specific endpoints ---


@router.get("/{bot_id}/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    bot_id: uuid.UUID,
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Goal completion rates, outcome breakdown, avg duration, red flag rate."""
    query = select(CallAnalytics).where(CallAnalytics.bot_id == bot_id, CallAnalytics.org_id == org_id)
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
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Paginated list of calls with goal outcomes."""
    query = select(CallAnalytics).where(CallAnalytics.bot_id == bot_id, CallAnalytics.org_id == org_id)
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
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Red flags grouped by severity with evidence quotes."""
    query = select(CallAnalytics).where(
        CallAnalytics.bot_id == bot_id,
        CallAnalytics.org_id == org_id,
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
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Unacknowledged critical/high red flags. Designed for GHL/n8n polling."""
    now = datetime.now(timezone.utc)

    query = (
        select(CallAnalytics)
        .where(
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.org_id == org_id,
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
            CallAnalytics.org_id == org_id,
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
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Mark a red flag alert as acknowledged."""
    result = await db.execute(
        select(CallAnalytics).where(
            CallAnalytics.id == analytics_id,
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.org_id == org_id,
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
    org_id: uuid.UUID = Depends(get_current_org),
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
            CallAnalytics.org_id == org_id,
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
    org_id: uuid.UUID = Depends(get_current_org),
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
        .where(CallAnalytics.bot_id == bot_id, CallAnalytics.org_id == org_id)
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
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Aggregated captured data per field. Enum fields: exact counts. String fields: raw values."""
    query = (
        select(CallAnalytics.captured_data, CallAnalytics.call_log_id)
        .where(
            CallAnalytics.bot_id == bot_id,
            CallAnalytics.org_id == org_id,
            CallAnalytics.captured_data.isnot(None),
        )
    )
    if start_date:
        query = query.where(CallAnalytics.created_at >= start_date)
    if end_date:
        query = query.where(CallAnalytics.created_at <= end_date)
    query = query.limit(1000)

    result = await db.execute(query)
    raw_rows = [(r[0], r[1]) for r in result.all() if r[0]]

    if not raw_rows:
        return []

    # Aggregate all field values with call_log_ids
    field_values: dict[str, list[tuple[str, str | None]]] = {}
    for captured, call_log_id in raw_rows:
        if not isinstance(captured, dict):
            continue
        for field_id, value in captured.items():
            if value is None:
                continue
            if field_id not in field_values:
                field_values[field_id] = []
            field_values[field_id].append((str(value), str(call_log_id) if call_log_id else None))

    summaries = []
    for field_id, entries in field_values.items():
        # Group by value
        value_groups: dict[str, dict] = {}
        for val, clid in entries:
            if val not in value_groups:
                value_groups[val] = {"count": 0, "call_log_ids": []}
            value_groups[val]["count"] += 1
            if clid:
                value_groups[val]["call_log_ids"].append(clid)

        sorted_values = sorted(value_groups.items(), key=lambda x: -x[1]["count"])
        summaries.append(CapturedDataFieldSummary(
            field_id=field_id,
            values=[
                {"value": v, "count": g["count"], "call_log_ids": g["call_log_ids"]}
                for v, g in sorted_values
            ],
            total_captured=len(entries),
        ))

    return summaries
