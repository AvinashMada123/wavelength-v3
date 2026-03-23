"""Extended billing tests — edge cases, resolve_call_duration, and bill_completed_call."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.services.billing import (
    calculate_call_credits,
    resolve_call_duration_seconds,
    bill_completed_call,
    check_org_credits,
    bill_ai_usage,
    ZERO_CREDITS,
    PER_MINUTE_RATE,
    MIN_BALANCE_TO_CALL,
)


def make_call_log(**overrides):
    base = {
        "id": "call-1",
        "call_sid": "sid-1",
        "org_id": "org-1",
        "contact_name": "Test User",
        "call_duration": None,
        "metadata_": {},
        "started_at": None,
        "ended_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# calculate_call_credits — extended edge cases
# ---------------------------------------------------------------------------

class TestCalculateCallCreditsExtended:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (None, ZERO_CREDITS),
            (0, ZERO_CREDITS),
            (-10, ZERO_CREDITS),
            (-1, ZERO_CREDITS),
            (1, Decimal("0.02")),
            (30, Decimal("0.50")),
            (60, Decimal("1.00")),
            (120, Decimal("2.00")),
            (90, Decimal("1.50")),
            (3600, Decimal("60.00")),
            (7, Decimal("0.12")),
            (45, Decimal("0.75")),
            (25, Decimal("0.42")),
        ],
        ids=[
            "none", "zero", "negative_10", "negative_1",
            "one_second", "30_seconds", "one_minute", "two_minutes",
            "90_seconds", "one_hour", "7_seconds", "45_seconds", "25_seconds",
        ],
    )
    def test_calculate_call_credits(self, seconds, expected):
        assert calculate_call_credits(seconds) == expected

    def test_precision_is_two_decimals(self):
        result = calculate_call_credits(7)
        assert result.as_tuple().exponent == -2


# ---------------------------------------------------------------------------
# resolve_call_duration_seconds — exhaustive fallback chain
# ---------------------------------------------------------------------------

class TestResolveDurationExtended:
    def test_provider_reported_takes_priority(self):
        cl = make_call_log(call_duration=100)
        assert resolve_call_duration_seconds(cl, reported_duration_seconds=200) == 200

    def test_provider_zero_skipped(self):
        """Zero reported → falls back to call_duration."""
        cl = make_call_log(call_duration=50)
        assert resolve_call_duration_seconds(cl, reported_duration_seconds=0) == 50

    def test_provider_negative_skipped(self):
        cl = make_call_log(call_duration=50)
        assert resolve_call_duration_seconds(cl, reported_duration_seconds=-5) == 50

    def test_call_duration_second_priority(self):
        cl = make_call_log(call_duration=75)
        assert resolve_call_duration_seconds(cl) == 75

    def test_call_duration_zero_skipped(self):
        cl = make_call_log(
            call_duration=0,
            metadata_={"call_metrics": {"total_duration_s": 88}},
        )
        assert resolve_call_duration_seconds(cl) == 88

    def test_metadata_metrics_third_priority(self):
        cl = make_call_log(metadata_={"call_metrics": {"total_duration_s": 42}})
        assert resolve_call_duration_seconds(cl) == 42

    def test_metadata_metrics_non_int_skipped(self):
        cl = make_call_log(metadata_={"call_metrics": {"total_duration_s": 42.5}})
        # float not isinstance int → skipped → falls through to None
        assert resolve_call_duration_seconds(cl) is None

    def test_metadata_metrics_zero_skipped(self):
        cl = make_call_log(metadata_={"call_metrics": {"total_duration_s": 0}})
        assert resolve_call_duration_seconds(cl) is None

    def test_metadata_missing_call_metrics(self):
        cl = make_call_log(metadata_={"other": "stuff"})
        assert resolve_call_duration_seconds(cl) is None

    def test_metadata_none(self):
        cl = make_call_log(metadata_=None)
        assert resolve_call_duration_seconds(cl) is None

    def test_timestamps_fourth_priority(self):
        start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=99)
        cl = make_call_log(started_at=start, ended_at=end)
        assert resolve_call_duration_seconds(cl) == 99

    def test_timestamps_zero_elapsed_returns_none(self):
        t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        cl = make_call_log(started_at=t, ended_at=t)
        assert resolve_call_duration_seconds(cl) is None

    def test_all_none_returns_none(self):
        cl = make_call_log()
        assert resolve_call_duration_seconds(cl) is None

    def test_only_started_at_returns_none(self):
        cl = make_call_log(started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert resolve_call_duration_seconds(cl) is None


# ---------------------------------------------------------------------------
# bill_completed_call — async tests
# ---------------------------------------------------------------------------

class TestBillCompletedCall:
    @pytest.mark.asyncio
    async def test_non_completed_status_returns_false(self):
        db = AsyncMock()
        cl = make_call_log()
        result = await bill_completed_call(
            db, cl, provider_status="failed", reported_duration_seconds=60
        )
        assert result is False
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_duration_skips_billing(self):
        db = AsyncMock()
        cl = make_call_log()
        result = await bill_completed_call(
            db, cl, provider_status="completed", reported_duration_seconds=0
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_none_duration_skips_billing(self):
        db = AsyncMock()
        cl = make_call_log()
        result = await bill_completed_call(
            db, cl, provider_status="completed"
        )
        assert result is False


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestBillingConstants:
    def test_zero_credits_is_zero(self):
        assert ZERO_CREDITS == Decimal("0.00")

    def test_per_minute_rate(self):
        assert PER_MINUTE_RATE == Decimal("1.00")

    def test_min_balance_is_one_minute(self):
        assert MIN_BALANCE_TO_CALL == PER_MINUTE_RATE


# ---------------------------------------------------------------------------
# bill_completed_call — success path tests (mocked DB)
# ---------------------------------------------------------------------------

class TestBillCompletedCallPaths:
    def _mock_db(self, execute_side_effects):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute_side_effects)
        return db

    @pytest.mark.asyncio
    async def test_duplicate_transaction_returns_true(self):
        """Existing transaction found → returns True without creating new tx."""
        existing_tx = SimpleNamespace(id="tx-existing")
        db = self._mock_db([
            # First execute: check for existing tx → found
            SimpleNamespace(scalar_one_or_none=lambda: existing_tx),
        ])
        cl = make_call_log(call_duration=60)
        result = await bill_completed_call(
            db, cl, provider_status="completed", reported_duration_seconds=60,
        )
        assert result is True
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_org_not_found_returns_false(self):
        db = self._mock_db([
            # First execute: no existing tx
            SimpleNamespace(scalar_one_or_none=lambda: None),
            # Second execute: org lookup → not found
            SimpleNamespace(scalar_one_or_none=lambda: None),
        ])
        cl = make_call_log(call_duration=60)
        result = await bill_completed_call(
            db, cl, provider_status="completed", reported_duration_seconds=60,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_insufficient_credits_returns_false(self):
        db = self._mock_db([
            # First execute: no existing tx
            SimpleNamespace(scalar_one_or_none=lambda: None),
            # Second execute: org found with low balance
            SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(
                credit_balance=Decimal("0.01"),
            )),
            # Third execute: double-check no existing tx (second check in source)
            SimpleNamespace(scalar_one_or_none=lambda: None),
        ])
        cl = make_call_log(call_duration=60)
        result = await bill_completed_call(
            db, cl, provider_status="completed", reported_duration_seconds=60,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_billing(self):
        org = SimpleNamespace(credit_balance=Decimal("100.00"))
        db = self._mock_db([
            # First execute: no existing tx
            SimpleNamespace(scalar_one_or_none=lambda: None),
            # Second execute: org found
            SimpleNamespace(scalar_one_or_none=lambda: org),
            # Third execute: double-check no existing tx
            SimpleNamespace(scalar_one_or_none=lambda: None),
        ])
        cl = make_call_log(call_duration=60, metadata_={})
        result = await bill_completed_call(
            db, cl, provider_status="completed", reported_duration_seconds=60,
        )
        assert result is True
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# check_org_credits
# ---------------------------------------------------------------------------

class TestCheckOrgCredits:
    @pytest.mark.asyncio
    async def test_balance_above_minimum(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: Decimal("10.00"))
        )
        has_credits, balance = await check_org_credits(db, "org-1")
        assert has_credits is True
        assert balance == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_balance_below_minimum(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: Decimal("0.50"))
        )
        has_credits, balance = await check_org_credits(db, "org-1")
        assert has_credits is False
        assert balance == Decimal("0.50")

    @pytest.mark.asyncio
    async def test_org_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
        )
        has_credits, balance = await check_org_credits(db, "org-missing")
        assert has_credits is False
        assert balance == ZERO_CREDITS


# ---------------------------------------------------------------------------
# bill_ai_usage
# ---------------------------------------------------------------------------

class TestBillAiUsage:
    @pytest.mark.asyncio
    async def test_zero_tokens_returns_false(self):
        db = AsyncMock()
        result = await bill_ai_usage(db, "org-1", tokens_used=0, model="claude-sonnet", reference="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_org_not_found_returns_false(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
        )
        result = await bill_ai_usage(
            db, "org-1", tokens_used=100_000, model="claude-sonnet", reference="test"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_success_deducts_credits(self):
        org = SimpleNamespace(credit_balance=Decimal("100.00"))
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: org)
        )
        result = await bill_ai_usage(
            db, "org-1", tokens_used=1_000_000, model="claude-sonnet", reference="test"
        )
        assert result is True
        db.add.assert_called_once()
        db.commit.assert_called_once()
