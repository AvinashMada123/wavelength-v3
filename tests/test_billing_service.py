from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *_args, **_kwargs: Mock()))

from app.services.billing import calculate_call_credits, resolve_call_duration_seconds


def make_call_log(**overrides):
    base = {
        "call_duration": None,
        "metadata_": {},
        "started_at": None,
        "ended_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_calculate_call_credits_rounds_up_started_minutes():
    assert calculate_call_credits(None) == Decimal("0.00")
    assert calculate_call_credits(0) == Decimal("0.00")
    assert calculate_call_credits(1) == Decimal("0.02")
    assert calculate_call_credits(60) == Decimal("1.00")
    assert calculate_call_credits(61) == Decimal("1.02")
    assert calculate_call_credits(90) == Decimal("1.50")
    assert calculate_call_credits(121) == Decimal("2.02")


def test_resolve_call_duration_prefers_provider_report():
    call_log = make_call_log(call_duration=45)
    assert resolve_call_duration_seconds(call_log, reported_duration_seconds=91) == 91


def test_resolve_call_duration_falls_back_to_metadata():
    call_log = make_call_log(metadata_={"call_metrics": {"total_duration_s": 88}})
    assert resolve_call_duration_seconds(call_log) == 88


def test_resolve_call_duration_falls_back_to_timestamps():
    started_at = datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(seconds=133)
    call_log = make_call_log(started_at=started_at, ended_at=ended_at)
    assert resolve_call_duration_seconds(call_log) == 133
