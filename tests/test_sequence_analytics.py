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
