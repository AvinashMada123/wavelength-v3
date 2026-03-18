# Sequence Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated analytics dashboard at `/sequences/analytics` with 7 backend API endpoints providing aggregated metrics, engagement scoring, and drill-down views for the sequence builder.

**Architecture:** New FastAPI router + service layer for analytics queries against existing sequence tables. In-memory cache with 5-min TTL. Frontend page using Recharts for visualization with overview + drill-down pattern.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, Next.js, Recharts, Tailwind/shadcn

**Spec:** `docs/superpowers/specs/2026-03-18-sequence-analytics-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/services/sequence_analytics.py` | Create | Cache layer, SQL aggregation queries, engagement scoring |
| `app/api/sequence_analytics.py` | Create | FastAPI router with 7 endpoints, Pydantic schemas |
| `app/main.py` | Modify | Register analytics router |
| `tests/test_sequence_analytics.py` | Create | Unit tests for scoring, caching, query helpers |
| `frontend/src/lib/sequences-api.ts` | Modify | Add analytics fetch functions |
| `frontend/src/app/(app)/sequences/analytics/page.tsx` | Create | Analytics dashboard page |
| `frontend/src/components/sequences/AnalyticsDrillDown.tsx` | Create | Template and lead drill-down views |

---

### Task 1: Cache Layer + Engagement Scoring Service

**Files:**
- Create: `app/services/sequence_analytics.py`
- Create: `tests/test_sequence_analytics.py`

This task builds the foundational service layer: the in-memory cache and the engagement scoring algorithm. These are pure functions with no DB dependencies, easy to test.

- [ ] **Step 1: Write failing tests for cache layer**

Create `tests/test_sequence_analytics.py`:

```python
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))

import time


def test_cache_set_and_get():
    from app.services.sequence_analytics import _cache_get, _cache_set, _cache

    _cache.clear()
    _cache_set("org1", "overview", {"a": "1"}, {"total": 10})
    result = _cache_get("org1", "overview", {"a": "1"})
    assert result == {"total": 10}


def test_cache_miss_returns_none():
    from app.services.sequence_analytics import _cache_get, _cache

    _cache.clear()
    result = _cache_get("org1", "overview", {"a": "1"})
    assert result is None


def test_cache_expired_returns_none():
    from app.services.sequence_analytics import _cache_get, _cache_set, _cache, CACHE_TTL_SECONDS

    _cache.clear()
    _cache_set("org1", "overview", {}, {"total": 10})
    # Manually expire the entry
    key = list(_cache.keys())[0]
    _cache[key] = (_cache[key][0], time.time() - CACHE_TTL_SECONDS - 1)
    result = _cache_get("org1", "overview", {})
    assert result is None


def test_cache_invalidate_org():
    from app.services.sequence_analytics import _cache_get, _cache_set, _cache, invalidate_cache

    _cache.clear()
    _cache_set("org1", "overview", {}, {"total": 10})
    _cache_set("org1", "channels", {}, {"channels": []})
    _cache_set("org2", "overview", {}, {"total": 5})
    invalidate_cache("org1")
    assert _cache_get("org1", "overview", {}) is None
    assert _cache_get("org1", "channels", {}) is None
    assert _cache_get("org2", "overview", {}) == {"total": 5}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_analytics.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement cache layer**

Create `app/services/sequence_analytics.py`:

```python
"""Sequence analytics service — caching, scoring, and query helpers."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 300  # 5 minutes

# dict of (cache_key) -> (data, expires_at_timestamp)
_cache: dict[str, tuple[Any, float]] = {}


def _make_cache_key(org_id: str, endpoint: str, params: dict) -> str:
    sorted_params = json.dumps(params, sort_keys=True, default=str)
    param_hash = hashlib.md5(sorted_params.encode()).hexdigest()
    return f"{org_id}:{endpoint}:{param_hash}"


def _cache_get(org_id: str, endpoint: str, params: dict) -> Any | None:
    key = _make_cache_key(org_id, endpoint, params)
    entry = _cache.get(key)
    if entry is None:
        return None
    data, expires_at = entry
    if time.time() > expires_at:
        del _cache[key]
        return None
    return data


def _cache_set(org_id: str, endpoint: str, params: dict, data: Any) -> None:
    key = _make_cache_key(org_id, endpoint, params)
    _cache[key] = (data, time.time() + CACHE_TTL_SECONDS)


def invalidate_cache(org_id: str) -> None:
    prefix = f"{org_id}:"
    keys_to_delete = [k for k in _cache if k.startswith(prefix)]
    for k in keys_to_delete:
        del _cache[k]
    if keys_to_delete:
        logger.info("cache_invalidated", org_id=org_id, keys_removed=len(keys_to_delete))
```

- [ ] **Step 4: Run cache tests to verify they pass**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_analytics.py::test_cache_set_and_get tests/test_sequence_analytics.py::test_cache_miss_returns_none tests/test_sequence_analytics.py::test_cache_expired_returns_none tests/test_sequence_analytics.py::test_cache_invalidate_org -v`
Expected: 4 PASS

- [ ] **Step 5: Write failing tests for engagement scoring**

Append to `tests/test_sequence_analytics.py`:

```python
from datetime import datetime, timedelta, timezone


def test_engagement_score_no_touchpoints():
    from app.services.sequence_analytics import compute_engagement_score

    result = compute_engagement_score(
        touchpoints=[],
        completed_sequences=0,
        total_sequences=0,
    )
    assert result["score"] == 0
    assert result["tier"] == "inactive"


def test_engagement_score_active_lead():
    from app.services.sequence_analytics import compute_engagement_score

    now = datetime.now(timezone.utc)
    touchpoints = [
        {"status": "replied", "sent_at": now - timedelta(hours=2), "updated_at": now - timedelta(hours=1), "expects_reply": True},
        {"status": "replied", "sent_at": now - timedelta(days=1), "updated_at": now - timedelta(hours=20), "expects_reply": True},
        {"status": "sent", "sent_at": now - timedelta(hours=5), "updated_at": now - timedelta(hours=5), "expects_reply": False},
    ]
    result = compute_engagement_score(
        touchpoints=touchpoints,
        completed_sequences=1,
        total_sequences=1,
    )
    assert result["score"] >= 70  # Should be hot
    assert result["tier"] == "hot"
    assert result["breakdown"]["activity"]["score"] > 0
    assert result["breakdown"]["recency"]["score"] > 0
    assert result["breakdown"]["outcome"]["score"] > 0


def test_engagement_score_only_failed():
    from app.services.sequence_analytics import compute_engagement_score

    now = datetime.now(timezone.utc)
    touchpoints = [
        {"status": "failed", "sent_at": None, "updated_at": now - timedelta(days=1), "expects_reply": False},
        {"status": "failed", "sent_at": None, "updated_at": now - timedelta(days=2), "expects_reply": False},
    ]
    result = compute_engagement_score(
        touchpoints=touchpoints,
        completed_sequences=0,
        total_sequences=1,
    )
    assert result["breakdown"]["activity"]["score"] == 0  # Clamped to 0
    assert result["tier"] in ("inactive", "cold")


def test_engagement_score_tier_boundaries():
    from app.services.sequence_analytics import _score_to_tier

    assert _score_to_tier(0) == "inactive"
    assert _score_to_tier(9) == "inactive"
    assert _score_to_tier(10) == "cold"
    assert _score_to_tier(39) == "cold"
    assert _score_to_tier(40) == "warm"
    assert _score_to_tier(69) == "warm"
    assert _score_to_tier(70) == "hot"
    assert _score_to_tier(100) == "hot"
```

- [ ] **Step 6: Implement engagement scoring**

Append to `app/services/sequence_analytics.py`:

```python
# ---------------------------------------------------------------------------
# Engagement Scoring
# ---------------------------------------------------------------------------
ACTIVITY_WEIGHT = 40
RECENCY_WEIGHT = 30
OUTCOME_WEIGHT = 30
ACTIVITY_CAP = 20
RECENCY_DECAY = 0.05


def _score_to_tier(score: int) -> str:
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    if score >= 10:
        return "cold"
    return "inactive"


def compute_engagement_score(
    touchpoints: list[dict],
    completed_sequences: int,
    total_sequences: int,
) -> dict:
    """Compute composite engagement score (0-100) from touchpoint data.

    Each touchpoint dict must have: status, sent_at, updated_at, expects_reply.
    """
    if not touchpoints:
        return {
            "score": 0,
            "tier": "inactive",
            "breakdown": {
                "activity": {"score": 0, "max": ACTIVITY_WEIGHT},
                "recency": {"score": 0, "max": RECENCY_WEIGHT},
                "outcome": {"score": 0, "max": OUTCOME_WEIGHT},
            },
        }

    now = datetime.now(timezone.utc)

    # --- Activity ---
    raw_activity = 0
    for tp in touchpoints:
        if tp["status"] == "replied":
            raw_activity += 3
        elif tp["status"] == "sent":
            raw_activity += 1
        elif tp["status"] == "failed":
            raw_activity -= 1
    raw_activity = max(raw_activity, 0)  # Clamp negative
    activity_score = round(min(raw_activity, ACTIVITY_CAP) / ACTIVITY_CAP * ACTIVITY_WEIGHT)

    # --- Recency ---
    most_recent = max(
        (tp["updated_at"] or tp["sent_at"] or now for tp in touchpoints),
        default=now,
    )
    if most_recent.tzinfo is None:
        most_recent = most_recent.replace(tzinfo=timezone.utc)
    days_since = max((now - most_recent).total_seconds() / 86400, 0)
    recency_score = round(math.exp(-RECENCY_DECAY * days_since) * RECENCY_WEIGHT)

    # --- Outcome ---
    completion_ratio = (completed_sequences / total_sequences) if total_sequences > 0 else 0
    reply_eligible = [tp for tp in touchpoints if tp.get("expects_reply")]
    replied_count = sum(1 for tp in reply_eligible if tp["status"] == "replied")
    reply_ratio = (replied_count / len(reply_eligible)) if reply_eligible else 0
    outcome_score = round(completion_ratio * 15 + reply_ratio * 15)

    total_score = min(activity_score + recency_score + outcome_score, 100)

    return {
        "score": total_score,
        "tier": _score_to_tier(total_score),
        "breakdown": {
            "activity": {"score": activity_score, "max": ACTIVITY_WEIGHT},
            "recency": {"score": recency_score, "max": RECENCY_WEIGHT},
            "outcome": {"score": outcome_score, "max": OUTCOME_WEIGHT},
        },
    }
```

- [ ] **Step 7: Run all tests to verify they pass**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_analytics.py -v`
Expected: 8 PASS

- [ ] **Step 8: Commit**

```bash
git add app/services/sequence_analytics.py tests/test_sequence_analytics.py
git commit -m "feat(analytics): add cache layer and engagement scoring service"
```

---

### Task 2: Analytics API Endpoints — Overview, Channels, Failures

**Files:**
- Create: `app/api/sequence_analytics.py`
- Modify: `app/main.py` (add router include)

This task builds the first 3 read-only endpoints that aggregate touchpoint data. No engagement scoring needed yet.

- [ ] **Step 1: Create the router with Pydantic schemas and overview endpoint**

Create `app/api/sequence_analytics.py`:

```python
"""Sequence analytics API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select, text
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

router = APIRouter(prefix="/api/sequences/analytics", tags=["sequence-analytics"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
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
    trend: TrendData = TrendData()


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
    count: int


class RetryStats(BaseModel):
    total_retried: int = 0
    retry_success_rate: float = 0.0


class FailuresResponse(BaseModel):
    total_failed: int = 0
    reasons: list[FailureReason] = []
    retry_stats: RetryStats = RetryStats()


# ---------------------------------------------------------------------------
# Helper: build common filters
# ---------------------------------------------------------------------------
def _build_touchpoint_filters(
    org_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    template_id: uuid.UUID | None,
    channel: str | None,
    bot_id: uuid.UUID | None,
) -> list:
    """Build WHERE clauses for touchpoint queries."""
    filters = [SequenceTouchpoint.org_id == org_id]
    if start_date:
        filters.append(SequenceTouchpoint.created_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc))
    if end_date:
        filters.append(SequenceTouchpoint.created_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc))
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
        # bot_id lives on SequenceTemplate, so subquery through instance -> template
        filters.append(
            SequenceTouchpoint.instance_id.in_(
                select(SequenceInstance.id).join(
                    SequenceTemplate, SequenceTemplate.id == SequenceInstance.template_id
                ).where(SequenceTemplate.bot_id == bot_id)
            )
        )
    return filters


def _filter_params_dict(
    start_date: date | None,
    end_date: date | None,
    template_id: uuid.UUID | None,
    channel: str | None,
    bot_id: uuid.UUID | None,
) -> dict:
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
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "overview", params)
    if cached:
        return cached

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # Exclude pending touchpoints from counts
    active_filters = filters + [SequenceTouchpoint.status.notin_(["pending", "generating", "scheduled"])]

    stats_q = select(
        func.count().filter(SequenceTouchpoint.status == "sent").label("sent"),
        func.count().filter(SequenceTouchpoint.status == "failed").label("failed"),
        func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
        func.count().filter(SequenceTouchpoint.status == "awaiting_reply").label("awaiting"),
    ).select_from(SequenceTouchpoint).where(*active_filters)
    row = (await db.execute(stats_q)).one()

    total_sent = (row.sent or 0) + (row.awaiting or 0) + (row.replied or 0)
    total_failed = row.failed or 0
    total_replied = row.replied or 0

    # Reply rate: only expects_reply touchpoints
    reply_q = select(
        func.count().label("total"),
        func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
    ).join(
        SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
    ).where(
        *active_filters,
        SequenceStep.expects_reply == True,
        SequenceTouchpoint.step_id.isnot(None),
    )
    reply_row = (await db.execute(reply_q)).one()
    reply_rate = (reply_row.replied / reply_row.total) if reply_row.total else 0.0

    # Completion rate
    inst_filters = [SequenceInstance.org_id == org_id]
    if start_date:
        inst_filters.append(SequenceInstance.started_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc))
    if end_date:
        inst_filters.append(SequenceInstance.started_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc))
    if template_id:
        inst_filters.append(SequenceInstance.template_id == template_id)

    inst_q = select(
        func.count().label("total"),
        func.count().filter(SequenceInstance.status == "completed").label("completed"),
    ).select_from(SequenceInstance).where(
        *inst_filters,
        SequenceInstance.status.notin_(["paused"]),
    )
    inst_row = (await db.execute(inst_q)).one()
    completion_rate = (inst_row.completed / inst_row.total) if inst_row.total else 0.0

    # Avg time to reply (approximate: updated_at - sent_at for replied touchpoints)
    reply_time_q = select(
        func.avg(
            func.extract("epoch", SequenceTouchpoint.updated_at) -
            func.extract("epoch", SequenceTouchpoint.sent_at)
        ).label("avg_seconds")
    ).where(
        *filters,
        SequenceTouchpoint.status == "replied",
        SequenceTouchpoint.sent_at.isnot(None),
    )
    avg_seconds = (await db.execute(reply_time_q)).scalar()
    avg_reply_hours = round(avg_seconds / 3600, 1) if avg_seconds else None

    # Trend: compare to equivalent previous period
    trend = TrendData()
    if start_date and end_date:
        period_days = (end_date - start_date).days + 1
        prev_start = start_date - timedelta(days=period_days)
        prev_end = start_date - timedelta(days=1)
        prev_filters = _build_touchpoint_filters(org_id, prev_start, prev_end, template_id, channel, bot_id)
        prev_active = prev_filters + [SequenceTouchpoint.status.notin_(["pending", "generating", "scheduled"])]

        prev_q = select(
            func.count().filter(SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"])).label("sent"),
            func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
        ).where(*prev_active)
        prev_row = (await db.execute(prev_q)).one()
        prev_sent = prev_row.sent or 0

        if prev_sent >= 5:
            trend.sent_change = round((total_sent - prev_sent) / prev_sent, 3) if prev_sent else None

            # Previous reply rate
            prev_reply_rate_q = select(
                func.count().label("total"),
                func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
            ).select_from(SequenceTouchpoint).join(
                SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
            ).where(
                *prev_active,
                SequenceStep.expects_reply == True,
                SequenceTouchpoint.step_id.isnot(None),
            )
            prev_rr = (await db.execute(prev_reply_rate_q)).one()
            prev_reply_rate = (prev_rr.replied / prev_rr.total) if prev_rr.total else 0
            trend.reply_rate_change = round(reply_rate - prev_reply_rate, 3)

            # Previous completion rate
            prev_inst_filters = [SequenceInstance.org_id == org_id]
            prev_inst_filters.append(SequenceInstance.started_at >= datetime.combine(prev_start, datetime.min.time(), tzinfo=timezone.utc))
            prev_inst_filters.append(SequenceInstance.started_at <= datetime.combine(prev_end, datetime.max.time(), tzinfo=timezone.utc))
            if template_id:
                prev_inst_filters.append(SequenceInstance.template_id == template_id)
            prev_inst_q = select(
                func.count().label("total"),
                func.count().filter(SequenceInstance.status == "completed").label("completed"),
            ).select_from(SequenceInstance).where(*prev_inst_filters, SequenceInstance.status.notin_(["paused"]))
            prev_inst = (await db.execute(prev_inst_q)).one()
            prev_completion = (prev_inst.completed / prev_inst.total) if prev_inst.total else 0
            trend.completion_rate_change = round(completion_rate - prev_completion, 3)

            # Previous avg reply time
            prev_reply_time_q = select(
                func.avg(
                    func.extract("epoch", SequenceTouchpoint.updated_at) -
                    func.extract("epoch", SequenceTouchpoint.sent_at)
                ).label("avg_seconds")
            ).select_from(SequenceTouchpoint).where(
                *prev_filters,
                SequenceTouchpoint.status == "replied",
                SequenceTouchpoint.sent_at.isnot(None),
            )
            prev_avg_seconds = (await db.execute(prev_reply_time_q)).scalar()
            if prev_avg_seconds and avg_seconds:
                prev_reply_hours = prev_avg_seconds / 3600
                trend.avg_reply_time_change = round(avg_reply_hours - prev_reply_hours, 1)

    result = OverviewResponse(
        total_sent=total_sent,
        total_failed=total_failed,
        total_replied=total_replied,
        reply_rate=round(reply_rate, 3),
        completion_rate=round(completion_rate, 3),
        avg_time_to_reply_hours=avg_reply_hours,
        trend=trend,
    )
    _cache_set(str(org_id), "overview", params, result.model_dump())
    return result


@router.get("/channels", response_model=ChannelsResponse)
async def get_channels(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "channels", params)
    if cached:
        return cached

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # Join with steps to get channel, group by channel
    q = select(
        SequenceStep.channel,
        func.count().filter(SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"])).label("sent"),
        func.count().filter(SequenceTouchpoint.status == "failed").label("failed"),
        func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
    ).join(
        SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
    ).where(
        *filters,
        SequenceTouchpoint.step_id.isnot(None),
        SequenceTouchpoint.status.notin_(["pending", "generating", "scheduled"]),
    ).group_by(SequenceStep.channel)

    rows = (await db.execute(q)).all()
    total_all = sum(r.sent for r in rows) or 1

    channels = [
        ChannelStats(
            channel=r.channel,
            sent=r.sent,
            failed=r.failed,
            replied=r.replied,
            reply_rate=round(r.replied / r.sent, 3) if r.sent else 0.0,
            percentage_of_total=round(r.sent / total_all, 3),
        )
        for r in rows
    ]

    result = ChannelsResponse(channels=channels)
    _cache_set(str(org_id), "channels", params, result.model_dump())
    return result


@router.get("/failures", response_model=FailuresResponse)
async def get_failures(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "failures", params)
    if cached:
        return cached

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # Total failed
    total_q = select(func.count()).where(*filters, SequenceTouchpoint.status == "failed")
    total_failed = (await db.execute(total_q)).scalar() or 0

    # Group by error_message (first 50 chars as bucket)
    reason_q = select(
        func.left(SequenceTouchpoint.error_message, 50).label("reason"),
        func.count().label("count"),
    ).where(
        *filters,
        SequenceTouchpoint.status == "failed",
        SequenceTouchpoint.error_message.isnot(None),
    ).group_by(
        func.left(SequenceTouchpoint.error_message, 50)
    ).order_by(func.count().desc()).limit(10)

    reason_rows = (await db.execute(reason_q)).all()
    reasons = [FailureReason(reason=r.reason, count=r.count) for r in reason_rows]

    # Retry stats
    retry_q = select(
        func.count().label("total_retried"),
        func.count().filter(SequenceTouchpoint.status != "failed").label("retry_success"),
    ).where(
        *filters,
        SequenceTouchpoint.retry_count > 0,
    )
    retry_row = (await db.execute(retry_q)).one()
    retry_success_rate = (retry_row.retry_success / retry_row.total_retried) if retry_row.total_retried else 0.0

    result = FailuresResponse(
        total_failed=total_failed,
        reasons=reasons,
        retry_stats=RetryStats(
            total_retried=retry_row.total_retried or 0,
            retry_success_rate=round(retry_success_rate, 3),
        ),
    )
    _cache_set(str(org_id), "failures", params, result.model_dump())
    return result
```

- [ ] **Step 2: Register the router in main.py**

In `app/main.py`, add the import and include_router call alongside the existing sequence router:

```python
from app.api import sequence_analytics
# ... (add near other router imports)

app.include_router(sequence_analytics.router)
```

- [ ] **Step 3: Verify the app starts without errors**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -c "from app.api.sequence_analytics import router; print('Router loaded:', len(router.routes), 'routes')"`
Expected: `Router loaded: 3 routes`

- [ ] **Step 4: Commit**

```bash
git add app/api/sequence_analytics.py app/main.py
git commit -m "feat(analytics): add overview, channels, failures API endpoints"
```

---

### Task 3: Analytics API Endpoints — Funnel, Templates

**Files:**
- Modify: `app/api/sequence_analytics.py`

Adds the funnel and template performance endpoints.

- [ ] **Step 1: Add Pydantic schemas for funnel and templates**

Append schemas to `app/api/sequence_analytics.py` (after existing schemas):

```python
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
```

- [ ] **Step 2: Add funnel endpoint**

Append to `app/api/sequence_analytics.py`:

```python
@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    template_id: uuid.UUID = Query(..., description="Required — funnels are per-template"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cached = _cache_get(str(org_id), "funnel", params)
    if cached:
        return cached

    # Get template name
    tmpl = (await db.execute(
        select(SequenceTemplate.name).where(
            SequenceTemplate.id == template_id,
            SequenceTemplate.org_id == org_id,
        )
    )).scalar()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)

    # Get step names from template
    steps_q = select(
        SequenceStep.step_order, SequenceStep.name
    ).where(
        SequenceStep.template_id == template_id
    ).order_by(SequenceStep.step_order)
    step_rows = (await db.execute(steps_q)).all()
    step_names = {s.step_order: s.name for s in step_rows}

    # Aggregate touchpoints by step_order
    tp_q = select(
        SequenceTouchpoint.step_order,
        func.count().filter(SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"])).label("sent"),
        func.count().filter(SequenceTouchpoint.status == "skipped").label("skipped"),
        func.count().filter(SequenceTouchpoint.status == "failed").label("failed"),
        func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
    ).where(*filters).group_by(
        SequenceTouchpoint.step_order
    ).order_by(SequenceTouchpoint.step_order)

    tp_rows = (await db.execute(tp_q)).all()

    # Total entered = instances for this template
    total_entered_q = select(func.count()).where(
        SequenceInstance.template_id == template_id,
        SequenceInstance.org_id == org_id,
    )
    if start_date:
        total_entered_q = total_entered_q.where(
            SequenceInstance.started_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        )
    if end_date:
        total_entered_q = total_entered_q.where(
            SequenceInstance.started_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        )
    total_entered = (await db.execute(total_entered_q)).scalar() or 0

    first_step_sent = tp_rows[0].sent if tp_rows else 0
    steps = []
    for r in tp_rows:
        drop_off = 1 - (r.sent / first_step_sent) if first_step_sent else 0.0
        steps.append(FunnelStep(
            step_order=r.step_order,
            name=step_names.get(r.step_order, f"Step {r.step_order}"),
            sent=r.sent,
            skipped=r.skipped,
            failed=r.failed,
            replied=r.replied,
            drop_off_rate=round(max(drop_off, 0), 3),
        ))

    result = FunnelResponse(template_name=tmpl, total_entered=total_entered, steps=steps)
    _cache_set(str(org_id), "funnel", params, result.model_dump())
    return result
```

- [ ] **Step 3: Add templates endpoint**

Append to `app/api/sequence_analytics.py`:

```python
@router.get("/templates", response_model=TemplatesResponse)
async def get_templates(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel: str | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    params = _filter_params_dict(start_date, end_date, None, channel, bot_id)
    cached = _cache_get(str(org_id), "templates", params)
    if cached:
        return cached

    # Get all templates for org
    tmpl_q = select(SequenceTemplate).where(SequenceTemplate.org_id == org_id)
    templates = (await db.execute(tmpl_q)).scalars().all()

    result_templates = []
    for tmpl in templates:
        # Instance stats
        inst_filters = [
            SequenceInstance.template_id == tmpl.id,
            SequenceInstance.org_id == org_id,
        ]
        if start_date:
            inst_filters.append(SequenceInstance.started_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc))
        if end_date:
            inst_filters.append(SequenceInstance.started_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc))

        inst_q = select(
            func.count().label("total"),
            func.count().filter(SequenceInstance.status == "completed").label("completed"),
            func.count().filter(SequenceInstance.status == "active").label("active"),
        ).where(*inst_filters, SequenceInstance.status.notin_(["paused"]))
        inst_row = (await db.execute(inst_q)).one()

        # Touchpoint stats
        tp_filters = _build_touchpoint_filters(org_id, start_date, end_date, tmpl.id, channel, bot_id)
        tp_q = select(
            func.count().filter(SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"])).label("sent"),
            func.count().filter(SequenceTouchpoint.status == "replied").label("replied"),
        ).where(*tp_filters, SequenceTouchpoint.status.notin_(["pending", "generating", "scheduled"]))
        tp_row = (await db.execute(tp_q)).one()

        # Step count
        step_count_q = select(func.count()).where(SequenceStep.template_id == tmpl.id)
        total_steps = (await db.execute(step_count_q)).scalar() or 0

        # Funnel summary: sent per step_order
        funnel_q = select(
            SequenceTouchpoint.step_order,
            func.count().filter(SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"])).label("sent"),
        ).where(*tp_filters).group_by(
            SequenceTouchpoint.step_order
        ).order_by(SequenceTouchpoint.step_order)
        funnel_rows = (await db.execute(funnel_q)).all()
        funnel_summary = [r.sent for r in funnel_rows]

        # Avg steps completed
        avg_steps = 0.0
        if inst_row.total:
            completed_tp_q = select(
                func.count(func.distinct(SequenceTouchpoint.step_order))
            ).join(
                SequenceInstance, SequenceInstance.id == SequenceTouchpoint.instance_id
            ).where(
                SequenceInstance.template_id == tmpl.id,
                SequenceTouchpoint.status.in_(["sent", "awaiting_reply", "replied"]),
            )
            total_steps_completed = (await db.execute(completed_tp_q)).scalar() or 0
            avg_steps = round(total_steps_completed / inst_row.total, 1) if inst_row.total else 0.0

        completion_rate = (inst_row.completed / inst_row.total) if inst_row.total else 0.0
        reply_rate = (tp_row.replied / tp_row.sent) if tp_row.sent else 0.0

        result_templates.append(TemplateStats(
            template_id=str(tmpl.id),
            name=tmpl.name,
            total_sent=tp_row.sent or 0,
            completion_rate=round(completion_rate, 3),
            reply_rate=round(reply_rate, 3),
            avg_steps_completed=avg_steps,
            total_steps=total_steps,
            active_instances=inst_row.active or 0,
            funnel_summary=funnel_summary,
        ))

    result = TemplatesResponse(templates=result_templates)
    _cache_set(str(org_id), "templates", params, result.model_dump())
    return result
```

- [ ] **Step 4: Verify routes loaded**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -c "from app.api.sequence_analytics import router; print('Router loaded:', len(router.routes), 'routes')"`
Expected: `Router loaded: 5 routes`

- [ ] **Step 5: Commit**

```bash
git add app/api/sequence_analytics.py
git commit -m "feat(analytics): add funnel and template performance endpoints"
```

---

### Task 4: Analytics API Endpoints — Leads + Lead Detail

**Files:**
- Modify: `app/api/sequence_analytics.py`

Adds the lead engagement table and single lead drill-down endpoints. These use the engagement scoring from Task 1.

- [ ] **Step 1: Add Pydantic schemas for leads**

Append to `app/api/sequence_analytics.py`:

```python
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
```

- [ ] **Step 2: Add leads list endpoint**

Append to `app/api/sequence_analytics.py`. This endpoint needs to import `compute_engagement_score` and the Lead model:

```python
from app.services.sequence_analytics import compute_engagement_score
# Add this import at the top of the file, alongside existing imports:
# Add at top of file: from app.models.lead import Lead

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
    sort_by: str = Query("score", description="Sort by: score, replies, last_interaction"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    # Cache key excludes pagination/sort — cache the full scored list, paginate from cache
    cache_params = _filter_params_dict(start_date, end_date, template_id, channel, bot_id)
    cache_params["tier"] = tier  # tier affects the dataset
    params = {**cache_params, "page": page, "page_size": page_size, "sort_by": sort_by, "sort_order": sort_order}
    cached = _cache_get(str(org_id), "leads", cache_params)
    if cached:
        # Apply sort + pagination to cached data
        cached_leads = cached["_scored_leads"]
        reverse = sort_order == "desc"
        if sort_by == "score":
            cached_leads.sort(key=lambda l: l["score"], reverse=reverse)
        elif sort_by == "replies":
            cached_leads.sort(key=lambda l: l["total_replies"], reverse=reverse)
        elif sort_by == "last_interaction":
            cached_leads.sort(key=lambda l: l["last_interaction_at"] or "", reverse=reverse)
        start_idx = (page - 1) * page_size
        return LeadsResponse(
            leads=[LeadStats(**l) for l in cached_leads[start_idx : start_idx + page_size]],
            tier_summary=TierSummary(**cached["tier_summary"]),
            total=len(cached_leads),
            page=page,
            page_size=page_size,
        )

    # Get all unique lead_ids with touchpoints in this org/period
    filters = _build_touchpoint_filters(org_id, start_date, end_date, template_id, channel, bot_id)
    lead_ids_q = select(func.distinct(SequenceTouchpoint.lead_id)).where(*filters)
    lead_id_rows = (await db.execute(lead_ids_q)).scalars().all()

    if not lead_id_rows:
        result = LeadsResponse()
        _cache_set(str(org_id), "leads", params, result.model_dump())
        return result

    # Batch fetch all touchpoints for these leads (avoids N+1)
    all_tp_q = select(
        SequenceTouchpoint.lead_id,
        SequenceTouchpoint.status,
        SequenceTouchpoint.sent_at,
        SequenceTouchpoint.updated_at,
        SequenceStep.expects_reply,
    ).select_from(SequenceTouchpoint).outerjoin(
        SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
    ).where(
        SequenceTouchpoint.lead_id.in_(lead_id_rows),
        SequenceTouchpoint.org_id == org_id,
    )
    all_tp_rows = (await db.execute(all_tp_q)).all()

    # Group touchpoints by lead_id
    from collections import defaultdict
    tp_by_lead: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in all_tp_rows:
        tp_by_lead[r.lead_id].append({
            "status": r.status, "sent_at": r.sent_at,
            "updated_at": r.updated_at, "expects_reply": r.expects_reply or False,
        })

    # Batch fetch instance stats per lead
    inst_q = select(
        SequenceInstance.lead_id,
        func.count().label("total"),
        func.count().filter(SequenceInstance.status == "completed").label("completed"),
        func.count().filter(SequenceInstance.status == "active").label("active"),
    ).select_from(SequenceInstance).where(
        SequenceInstance.lead_id.in_(lead_id_rows),
        SequenceInstance.org_id == org_id,
    ).group_by(SequenceInstance.lead_id)
    inst_rows = (await db.execute(inst_q)).all()
    inst_by_lead = {r.lead_id: r for r in inst_rows}

    # Batch fetch lead info
    lead_info_q = select(Lead.id, Lead.contact_name, Lead.phone_number).where(Lead.id.in_(lead_id_rows))
    lead_info_rows = (await db.execute(lead_info_q)).all()
    lead_info_by_id = {r.id: r for r in lead_info_rows}

    # Compute scores
    scored_leads = []
    for lid in lead_id_rows:
        touchpoints = tp_by_lead.get(lid, [])
        inst = inst_by_lead.get(lid)
        lead_info = lead_info_by_id.get(lid)

        score_data = compute_engagement_score(
            touchpoints,
            inst.completed if inst else 0,
            inst.total if inst else 0,
        )

        total_replies = sum(1 for tp in touchpoints if tp["status"] == "replied")
        last_interaction = max(
            (tp["updated_at"] for tp in touchpoints if tp["updated_at"]),
            default=None,
        )

        scored_leads.append({
            "lead_id": str(lid),
            "lead_name": lead_info.contact_name if lead_info else None,
            "lead_phone": lead_info.phone_number if lead_info else None,
            "score": score_data["score"],
            "tier": score_data["tier"],
            "active_sequences": (inst.active if inst else 0) or 0,
            "total_replies": total_replies,
            "last_interaction_at": last_interaction.isoformat() if last_interaction else None,
        })

    # Tier summary (computed BEFORE tier filtering to show full distribution)
    tier_summary = TierSummary(
        hot=sum(1 for l in scored_leads if l["tier"] == "hot"),
        warm=sum(1 for l in scored_leads if l["tier"] == "warm"),
        cold=sum(1 for l in scored_leads if l["tier"] == "cold"),
        inactive=sum(1 for l in scored_leads if l["tier"] == "inactive"),
    )

    # Filter by tier if specified (after computing summary)
    if tier:
        scored_leads = [l for l in scored_leads if l["tier"] == tier]

    # Sort
    reverse = sort_order == "desc"
    if sort_by == "score":
        scored_leads.sort(key=lambda l: l["score"], reverse=reverse)
    elif sort_by == "replies":
        scored_leads.sort(key=lambda l: l["total_replies"], reverse=reverse)
    elif sort_by == "last_interaction":
        scored_leads.sort(key=lambda l: l["last_interaction_at"] or "", reverse=reverse)

    # Paginate
    total = len(scored_leads)
    start = (page - 1) * page_size
    page_leads = scored_leads[start : start + page_size]

    # Cache the full scored list + tier summary (pagination applied on retrieval)
    _cache_set(str(org_id), "leads", cache_params, {
        "_scored_leads": scored_leads,
        "tier_summary": tier_summary.model_dump(),
    })

    result = LeadsResponse(
        leads=[LeadStats(**l) for l in page_leads],
        tier_summary=tier_summary,
        total=total,
        page=page,
        page_size=page_size,
    )
    return result
```

**Important:** Check the actual Lead model import path. Likely `from app.models.lead import Lead` or check via `grep -r "class Lead" app/models/`.

- [ ] **Step 3: Add lead detail endpoint**

Append to `app/api/sequence_analytics.py`:

```python
@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead_detail(
    lead_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    cached = _cache_get(str(org_id), f"lead:{lead_id}", {})
    if cached:
        return cached

    # Verify lead belongs to org (via touchpoints)
    exists = (await db.execute(
        select(func.count()).where(
            SequenceTouchpoint.lead_id == lead_id,
            SequenceTouchpoint.org_id == org_id,
        )
    )).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Lead info
    lead_q = select(Lead.contact_name).where(Lead.id == lead_id)
    lead_info = (await db.execute(lead_q)).first()

    # Touchpoints for scoring
    tp_q = select(
        SequenceTouchpoint.status,
        SequenceTouchpoint.sent_at,
        SequenceTouchpoint.updated_at,
        SequenceStep.expects_reply,
    ).outerjoin(
        SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
    ).where(
        SequenceTouchpoint.lead_id == lead_id,
        SequenceTouchpoint.org_id == org_id,
    )
    tp_rows = (await db.execute(tp_q)).all()
    touchpoints = [
        {"status": r.status, "sent_at": r.sent_at, "updated_at": r.updated_at, "expects_reply": r.expects_reply or False}
        for r in tp_rows
    ]

    # Instance stats
    inst_q = select(
        func.count().label("total"),
        func.count().filter(SequenceInstance.status == "completed").label("completed"),
        func.count().filter(SequenceInstance.status == "active").label("active"),
    ).where(SequenceInstance.lead_id == lead_id, SequenceInstance.org_id == org_id)
    inst_row = (await db.execute(inst_q)).one()

    score_data = compute_engagement_score(touchpoints, inst_row.completed or 0, inst_row.total or 0)

    total_replies = sum(1 for tp in touchpoints if tp["status"] == "replied")

    # Avg reply time
    reply_times = []
    for tp in touchpoints:
        if tp["status"] == "replied" and tp["sent_at"] and tp["updated_at"]:
            diff = (tp["updated_at"] - tp["sent_at"]).total_seconds()
            if diff > 0:
                reply_times.append(diff)
    avg_reply_hours = round(sum(reply_times) / len(reply_times) / 3600, 1) if reply_times else None

    # Timeline
    timeline_q = select(
        SequenceTouchpoint.sent_at,
        SequenceTouchpoint.updated_at,
        SequenceTouchpoint.status,
        SequenceTouchpoint.generated_content,
        SequenceTouchpoint.reply_text,
        SequenceTouchpoint.step_order,
        SequenceStep.name.label("step_name"),
        SequenceStep.channel,
        SequenceTemplate.name.label("template_name"),
    ).outerjoin(
        SequenceStep, SequenceStep.id == SequenceTouchpoint.step_id
    ).join(
        SequenceInstance, SequenceInstance.id == SequenceTouchpoint.instance_id
    ).join(
        SequenceTemplate, SequenceTemplate.id == SequenceInstance.template_id
    ).where(
        SequenceTouchpoint.lead_id == lead_id,
        SequenceTouchpoint.org_id == org_id,
    ).order_by(SequenceTouchpoint.created_at.asc())

    timeline_rows = (await db.execute(timeline_q)).all()
    timeline = [
        TimelineEntry(
            timestamp=(r.sent_at or r.updated_at).isoformat() if (r.sent_at or r.updated_at) else "",
            template_name=r.template_name or "Unknown",
            step_name=r.step_name or f"Step {r.step_order}",
            channel=r.channel or "unknown",
            status=r.status,
            content_preview=r.generated_content[:80] if r.generated_content else None,
            reply_text=r.reply_text,
        )
        for r in timeline_rows
    ]

    result = LeadDetailResponse(
        lead_id=str(lead_id),
        lead_name=lead_info.contact_name if lead_info else None,
        score=score_data["score"],
        tier=score_data["tier"],
        score_breakdown=ScoreBreakdown(
            activity=ScoreDimension(**score_data["breakdown"]["activity"]),
            recency=ScoreDimension(**score_data["breakdown"]["recency"]),
            outcome=ScoreDimension(**score_data["breakdown"]["outcome"]),
        ),
        active_sequences=inst_row.active or 0,
        total_replies=total_replies,
        avg_reply_time_hours=avg_reply_hours,
        timeline=timeline,
    )
    _cache_set(str(org_id), f"lead:{lead_id}", {}, result.model_dump())
    return result
```

- [ ] **Step 4: Verify all 7 routes loaded**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -c "from app.api.sequence_analytics import router; print('Router loaded:', len(router.routes), 'routes')"`
Expected: `Router loaded: 7 routes`

- [ ] **Step 5: Commit**

```bash
git add app/api/sequence_analytics.py
git commit -m "feat(analytics): add leads engagement and lead detail endpoints"
```

---

### Task 5: Frontend API Client Functions

**Files:**
- Modify: `frontend/src/lib/sequences-api.ts`

Adds TypeScript types and fetch functions for all analytics endpoints.

- [ ] **Step 1: Add analytics types and fetch functions**

Append to `frontend/src/lib/sequences-api.ts`:

```typescript
// ---------------------------------------------------------------------------
// Analytics Types
// ---------------------------------------------------------------------------
export interface AnalyticsFilters {
  start_date?: string;
  end_date?: string;
  template_id?: string;
  channel?: string;
  bot_id?: string;
}

export interface TrendData {
  sent_change: number | null;
  reply_rate_change: number | null;
  completion_rate_change: number | null;
  avg_reply_time_change: number | null;
}

export interface AnalyticsOverview {
  total_sent: number;
  total_failed: number;
  total_replied: number;
  reply_rate: number;
  completion_rate: number;
  avg_time_to_reply_hours: number | null;
  trend: TrendData;
}

export interface ChannelStats {
  channel: string;
  sent: number;
  failed: number;
  replied: number;
  reply_rate: number;
  percentage_of_total: number;
}

export interface FunnelStep {
  step_order: number;
  name: string;
  sent: number;
  skipped: number;
  failed: number;
  replied: number;
  drop_off_rate: number;
}

export interface FunnelData {
  template_name: string;
  total_entered: number;
  steps: FunnelStep[];
}

export interface TemplateStats {
  template_id: string;
  name: string;
  total_sent: number;
  completion_rate: number;
  reply_rate: number;
  avg_steps_completed: number;
  total_steps: number;
  active_instances: number;
  funnel_summary: number[];
}

export interface LeadStats {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string | null;
  score: number;
  tier: string;
  active_sequences: number;
  total_replies: number;
  last_interaction_at: string | null;
}

export interface TierSummary {
  hot: number;
  warm: number;
  cold: number;
  inactive: number;
}

export interface LeadsData {
  leads: LeadStats[];
  tier_summary: TierSummary;
  total: number;
  page: number;
  page_size: number;
}

export interface ScoreBreakdown {
  activity: { score: number; max: number };
  recency: { score: number; max: number };
  outcome: { score: number; max: number };
}

export interface TimelineEntry {
  timestamp: string;
  template_name: string;
  step_name: string;
  channel: string;
  status: string;
  content_preview: string | null;
  reply_text: string | null;
}

export interface LeadDetail {
  lead_id: string;
  lead_name: string | null;
  score: number;
  tier: string;
  score_breakdown: ScoreBreakdown;
  active_sequences: number;
  total_replies: number;
  avg_reply_time_hours: number | null;
  timeline: TimelineEntry[];
}

export interface FailureReason {
  reason: string;
  count: number;
}

export interface FailuresData {
  total_failed: number;
  reasons: FailureReason[];
  retry_stats: {
    total_retried: number;
    retry_success_rate: number;
  };
}

// ---------------------------------------------------------------------------
// Analytics Fetch Functions
// ---------------------------------------------------------------------------
function buildAnalyticsQS(filters?: AnalyticsFilters): string {
  const qs = new URLSearchParams();
  if (filters?.start_date) qs.set("start_date", filters.start_date);
  if (filters?.end_date) qs.set("end_date", filters.end_date);
  if (filters?.template_id) qs.set("template_id", filters.template_id);
  if (filters?.channel) qs.set("channel", filters.channel);
  if (filters?.bot_id) qs.set("bot_id", filters.bot_id);
  return qs.toString();
}

export const fetchAnalyticsOverview = (filters?: AnalyticsFilters) =>
  apiFetch<AnalyticsOverview>(`/api/sequences/analytics/overview?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsChannels = (filters?: AnalyticsFilters) =>
  apiFetch<{ channels: ChannelStats[] }>(`/api/sequences/analytics/channels?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsTemplates = (filters?: AnalyticsFilters) =>
  apiFetch<{ templates: TemplateStats[] }>(`/api/sequences/analytics/templates?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsFunnel = (templateId: string, filters?: AnalyticsFilters) =>
  apiFetch<FunnelData>(`/api/sequences/analytics/funnel?template_id=${templateId}&${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsLeads = (
  filters?: AnalyticsFilters & { tier?: string; page?: number; page_size?: number; sort_by?: string; sort_order?: string }
) => {
  const qs = new URLSearchParams();
  if (filters?.start_date) qs.set("start_date", filters.start_date);
  if (filters?.end_date) qs.set("end_date", filters.end_date);
  if (filters?.template_id) qs.set("template_id", filters.template_id);
  if (filters?.channel) qs.set("channel", filters.channel);
  if (filters?.tier) qs.set("tier", filters.tier);
  if (filters?.page) qs.set("page", String(filters.page));
  if (filters?.page_size) qs.set("page_size", String(filters.page_size));
  if (filters?.sort_by) qs.set("sort_by", filters.sort_by);
  if (filters?.sort_order) qs.set("sort_order", filters.sort_order);
  return apiFetch<LeadsData>(`/api/sequences/analytics/leads?${qs}`);
};

export const fetchAnalyticsLeadDetail = (leadId: string) =>
  apiFetch<LeadDetail>(`/api/sequences/analytics/leads/${leadId}`);

export const fetchAnalyticsFailures = (filters?: AnalyticsFilters) =>
  apiFetch<FailuresData>(`/api/sequences/analytics/failures?${buildAnalyticsQS(filters)}`);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/sequences-api.ts
git commit -m "feat(analytics): add frontend API client for analytics endpoints"
```

---

### Task 6: Frontend Analytics Dashboard Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/analytics/page.tsx`

This is the main analytics page with filter bar, KPI cards, charts, and tables. Uses the overview + drill-down pattern.

- [ ] **Step 1: Create the analytics page**

Create `frontend/src/app/(app)/sequences/analytics/page.tsx`. This is a large file — build it in sections.

The page should include:
1. **Filter bar** at the top with:
   - Date range inputs (start/end)
   - Preset buttons (7d, 30d, 90d, All)
   - Template dropdown (populated from `/templates` response)
   - Channel dropdown (whatsapp_template, whatsapp_session, sms, voice_call)
2. **KPI cards row** showing: Total Sent, Reply Rate, Completion Rate, Avg Reply Time — each with trend arrow
3. **Charts row**: Delivery trend (Recharts BarChart) + Channel breakdown (horizontal bars)
4. **Bottom row**: Template performance table (clickable rows) + Lead engagement summary (tier cards + lead list)
5. **Drill-down state**: When a template or lead is clicked, show `AnalyticsDrillDown` component instead of overview

Key implementation details:
- Use `"use client"` directive
- Import from `@/components/ui/card`, `@/components/ui/button`, `@/components/ui/badge`, `@/components/ui/select`, `@/components/ui/table`, `@/components/ui/skeleton`
- Import `Header` from `@/components/layout/header` and `PageTransition` from `@/components/layout/page-transition`
- Import Recharts: `BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer`
- Use `Promise.allSettled` for parallel data fetching
- Manage filter state with `useState`, sync to URL with `useSearchParams`
- Format dates with `date-fns` (`format`, `subDays`)
- Use `toast` from `sonner` for error notifications

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  BarChart3, TrendingUp, TrendingDown, Minus, ArrowLeft,
  MessageSquare, Phone, Mail, Loader2, RefreshCw,
} from "lucide-react";
import { format, subDays } from "date-fns";
import { toast } from "sonner";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  type AnalyticsFilters,
  type AnalyticsOverview,
  type ChannelStats,
  type TemplateStats,
  type LeadsData,
  type FunnelData,
  type FailuresData,
  type LeadDetail,
  fetchAnalyticsOverview,
  fetchAnalyticsChannels,
  fetchAnalyticsTemplates,
  fetchAnalyticsLeads,
  fetchAnalyticsFunnel,
  fetchAnalyticsFailures,
  fetchAnalyticsLeadDetail,
} from "@/lib/sequences-api";
import { AnalyticsDrillDown } from "@/components/sequences/AnalyticsDrillDown";
```

The page component manages:
- `filters` state (AnalyticsFilters)
- `overview`, `channels`, `templates`, `leads` data states
- `drillDown` state: `{ type: "template" | "lead", id: string } | null`
- `loading` boolean
- Drill-down data: `funnelData`, `failuresData`, `leadDetail`

**Data loading pattern:**
```typescript
const loadData = useCallback(async () => {
  setLoading(true);
  const results = await Promise.allSettled([
    fetchAnalyticsOverview(filters),
    fetchAnalyticsChannels(filters),
    fetchAnalyticsTemplates(filters),
    fetchAnalyticsLeads(filters),
  ]);
  if (results[0].status === "fulfilled") setOverview(results[0].value);
  if (results[1].status === "fulfilled") setChannels(results[1].value.channels);
  if (results[2].status === "fulfilled") setTemplates(results[2].value.templates);
  if (results[3].status === "fulfilled") setLeads(results[3].value);
  setLoading(false);
}, [filters]);
```

**Preset button handler:**
```typescript
const setPreset = (days: number | null) => {
  if (days === null) {
    setFilters(f => ({ ...f, start_date: undefined, end_date: undefined }));
  } else {
    const end = format(new Date(), "yyyy-MM-dd");
    const start = format(subDays(new Date(), days), "yyyy-MM-dd");
    setFilters(f => ({ ...f, start_date: start, end_date: end }));
  }
};
```

**KPI Card helper:**
```typescript
function KPICard({ label, value, trend, format: fmt }: {
  label: string; value: number | null; trend: number | null; format?: "percent" | "hours" | "number";
}) {
  const formatted = value === null ? "—" :
    fmt === "percent" ? `${(value * 100).toFixed(1)}%` :
    fmt === "hours" ? `${value}h` :
    value.toLocaleString();
  const trendIcon = trend === null ? <Minus className="h-3 w-3" /> :
    trend > 0 ? <TrendingUp className="h-3 w-3 text-green-500" /> :
    trend < 0 ? <TrendingDown className="h-3 w-3 text-red-500" /> :
    <Minus className="h-3 w-3" />;
  const trendText = trend === null ? "—" :
    `${trend > 0 ? "+" : ""}${(trend * 100).toFixed(1)}%`;

  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-bold mt-1">{formatted}</p>
        <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground">
          {trendIcon} <span>{trendText} vs prev period</span>
        </div>
      </CardContent>
    </Card>
  );
}
```

**Template row click → drill-down:**
```typescript
const handleTemplateClick = async (templateId: string) => {
  setDrillDown({ type: "template", id: templateId });
  const [funnel, failures] = await Promise.allSettled([
    fetchAnalyticsFunnel(templateId, filters),
    fetchAnalyticsFailures(filters),
  ]);
  if (funnel.status === "fulfilled") setFunnelData(funnel.value);
  if (failures.status === "fulfilled") setFailuresData(failures.value);
};
```

**Lead row click → drill-down:**
```typescript
const handleLeadClick = async (leadId: string) => {
  setDrillDown({ type: "lead", id: leadId });
  const detail = await fetchAnalyticsLeadDetail(leadId);
  setLeadDetail(detail);
};
```

Build the full page with all these sections. Use Skeleton components for loading states. The channel breakdown should use simple CSS bars (not a full Recharts chart — keep it simple).

- [ ] **Step 2: Verify the page renders without errors**

Run: `cd "/Users/animeshmahato/Wavelength v3/frontend" && npx next lint src/app/\\(app\\)/sequences/analytics/page.tsx`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/analytics/page.tsx
git commit -m "feat(analytics): add analytics dashboard page with filters, KPIs, charts, tables"
```

---

### Task 7: Frontend Drill-Down Component

**Files:**
- Create: `frontend/src/components/sequences/AnalyticsDrillDown.tsx`

Renders template detail (funnel + failures) or lead detail (score + timeline) views.

- [ ] **Step 1: Create the drill-down component**

Create `frontend/src/components/sequences/AnalyticsDrillDown.tsx`:

The component accepts:
```typescript
interface AnalyticsDrillDownProps {
  type: "template" | "lead";
  onBack: () => void;
  // Template mode
  funnelData?: FunnelData | null;
  failuresData?: FailuresData | null;
  // Lead mode
  leadDetail?: LeadDetail | null;
}
```

**Template mode renders:**
1. Back button + template name header
2. KPI cards: Total Entered, Completed (%), Reply Rate, (from funnel + failures data)
3. Step funnel: horizontal bars showing sent count per step with step name, skipped/failed counts, drop-off rate
4. Failure reasons table
5. Retry stats

**Lead mode renders:**
1. Back button + lead name + score badge
2. Score breakdown: 3 progress bars for activity/recency/outcome with score/max labels
3. Quick stats cards: Active Sequences, Total Replies, Avg Reply Time
4. Timeline: vertical timeline with dots, showing each touchpoint's template, step, channel, status, content preview, reply text

Use `Badge` for status/tier display. Color-code tiers: hot=green, warm=yellow, cold=blue, inactive=gray.

Channel badges: whatsapp_template=green, whatsapp_session=emerald, sms=blue, voice_call=purple.

- [ ] **Step 2: Verify lint passes**

Run: `cd "/Users/animeshmahato/Wavelength v3/frontend" && npx next lint src/components/sequences/AnalyticsDrillDown.tsx`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sequences/AnalyticsDrillDown.tsx
git commit -m "feat(analytics): add drill-down component for template and lead detail views"
```

---

### Task 8: Navigation Link + Final Integration

**Files:**
- Modify: `frontend/src/app/(app)/sequences/page.tsx` (add Analytics nav link)
- Modify: `frontend/src/app/(app)/sequences/monitor/page.tsx` (add Analytics nav link)

- [ ] **Step 1: Find navigation pattern in sequences pages**

Read the sequences page and monitor page to find where the nav links (Templates, Monitor) are rendered. Add an "Analytics" link pointing to `/sequences/analytics`.

Look for existing nav links like:
```typescript
<Link href="/sequences">Templates</Link>
<Link href="/sequences/monitor">Monitor</Link>
```

Add alongside them:
```typescript
<Link href="/sequences/analytics">Analytics</Link>
```

Use the same styling pattern (Button variant, icon, etc.) as the existing links.

- [ ] **Step 2: Add Analytics link to sequences page**

Edit the nav section in `frontend/src/app/(app)/sequences/page.tsx` to include the Analytics link.

- [ ] **Step 3: Add Analytics link to monitor page**

Edit the nav section in `frontend/src/app/(app)/sequences/monitor/page.tsx` to include the Analytics link.

- [ ] **Step 4: Verify frontend builds**

Run: `cd "/Users/animeshmahato/Wavelength v3/frontend" && npx next build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/page.tsx frontend/src/app/\(app\)/sequences/monitor/page.tsx
git commit -m "feat(analytics): add analytics navigation link to sequences pages"
```

---

### Task 9: End-to-End Verification

- [ ] **Step 1: Start the backend and verify endpoints respond**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -c "
from app.api.sequence_analytics import router
print('Endpoints:')
for route in router.routes:
    print(f'  {route.methods} {route.path}')
"`

Expected: All 7 endpoints listed.

- [ ] **Step 2: Run all tests**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_analytics.py -v`
Expected: All 8 tests pass.

- [ ] **Step 3: Verify frontend build**

Run: `cd "/Users/animeshmahato/Wavelength v3/frontend" && npx next build`
Expected: Build succeeds with no errors.

- [ ] **Step 4: Manual smoke test (if server is running)**

Open `http://localhost:3000/sequences/analytics` and verify:
- Page loads without errors
- Filter bar renders with presets
- KPI cards show (may be zeros if no data)
- No console errors
