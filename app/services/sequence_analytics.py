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
