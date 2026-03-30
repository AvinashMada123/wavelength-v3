"""Tests for callback time parsing — TDD.

Covers: relative time, day-of-week, "next week", "this afternoon",
combined day+time, regressions, and calling window enforcement.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.callback_scheduler import enforce_calling_window, parse_callback_time

TZ = "Asia/Kolkata"
_TZ = ZoneInfo(TZ)


def _make_now(year=2026, month=3, day=25, hour=14, minute=0, weekday_name="Wednesday"):
    """Create a timezone-aware datetime. March 25, 2026 = Wednesday."""
    return datetime(year, month, day, hour, minute, 0, tzinfo=_TZ)


# ---------------------------------------------------------------------------
# Day-of-week parsing
# ---------------------------------------------------------------------------


class TestDayOfWeek:

    def test_monday_from_wednesday(self):
        """'Monday' on Wednesday → next Monday 10 AM."""
        now = _make_now()  # Wed Mar 25
        result = parse_callback_time("Monday", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 0  # Monday
        assert result.astimezone(_TZ).hour == 10
        # Should be Mar 30 (5 days ahead)
        assert result.astimezone(_TZ).day == 30

    def test_monday_on_monday_pushes_to_next_week(self):
        """'Monday' on a Monday → next Monday (7 days), not today."""
        now = datetime(2026, 3, 30, 14, 0, 0, tzinfo=_TZ)  # Monday
        result = parse_callback_time("Monday", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 0
        expected_day = 30 + 7  # April 6
        assert result.astimezone(_TZ).month == 4
        assert result.astimezone(_TZ).day == 6

    def test_on_friday_from_tuesday(self):
        """'on Friday' from Tuesday → this Friday 10 AM."""
        now = datetime(2026, 3, 24, 10, 0, 0, tzinfo=_TZ)  # Tuesday
        result = parse_callback_time("on Friday", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 4  # Friday
        assert result.astimezone(_TZ).day == 27
        assert result.astimezone(_TZ).hour == 10

    def test_next_wednesday_from_monday(self):
        """'next Wednesday' from Monday → this Wednesday 10 AM."""
        now = datetime(2026, 3, 30, 10, 0, 0, tzinfo=_TZ)  # Monday
        result = parse_callback_time("next Wednesday", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 2  # Wednesday
        assert result.astimezone(_TZ).month == 4
        assert result.astimezone(_TZ).day == 1

    def test_monday_morning(self):
        """'Monday morning' → next Monday 10 AM."""
        now = _make_now()  # Wed
        result = parse_callback_time("Monday morning", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 0
        assert result.astimezone(_TZ).hour == 10

    def test_friday_afternoon(self):
        """'Friday afternoon' → this Friday 2 PM."""
        now = datetime(2026, 3, 24, 10, 0, 0, tzinfo=_TZ)  # Tuesday
        result = parse_callback_time("Friday afternoon", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 4
        assert result.astimezone(_TZ).hour == 14

    def test_wednesday_evening(self):
        """'Wednesday evening' → this Wednesday 6 PM."""
        now = datetime(2026, 3, 30, 10, 0, 0, tzinfo=_TZ)  # Monday
        result = parse_callback_time("Wednesday evening", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 2
        assert result.astimezone(_TZ).hour == 18

    def test_monday_at_3pm(self):
        """'Monday at 3 PM' → next Monday 15:00."""
        now = _make_now()  # Wed
        result = parse_callback_time("Monday at 3 PM", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 0
        assert result.astimezone(_TZ).hour == 15


# ---------------------------------------------------------------------------
# Relative day references
# ---------------------------------------------------------------------------


class TestRelativeDays:

    def test_next_week(self):
        """'next week' → next Monday 10 AM."""
        now = _make_now()  # Wed Mar 25
        result = parse_callback_time("next week", TZ, now=now)
        assert result.astimezone(_TZ).weekday() == 0  # Monday
        assert result.astimezone(_TZ).hour == 10
        assert result.astimezone(_TZ).day == 30

    def test_day_after_tomorrow(self):
        """'day after tomorrow' → now + 2 days at 10 AM."""
        now = _make_now()  # Wed Mar 25
        result = parse_callback_time("day after tomorrow", TZ, now=now)
        assert result.astimezone(_TZ).day == 27
        assert result.astimezone(_TZ).hour == 10

    def test_couple_of_days(self):
        """'in a couple of days' → now + 2 days at 10 AM."""
        now = _make_now()  # Wed Mar 25
        result = parse_callback_time("in a couple of days", TZ, now=now)
        assert result.astimezone(_TZ).day == 27
        assert result.astimezone(_TZ).hour == 10

    def test_few_days(self):
        """'in a few days' → now + 3 days at 10 AM."""
        now = _make_now()  # Wed Mar 25
        result = parse_callback_time("in a few days", TZ, now=now)
        assert result.astimezone(_TZ).day == 28
        assert result.astimezone(_TZ).hour == 10


# ---------------------------------------------------------------------------
# "This afternoon/evening"
# ---------------------------------------------------------------------------


class TestThisTimeOfDay:

    def test_this_afternoon_before_2pm(self):
        """'this afternoon' at 11 AM → same day 14:00."""
        now = datetime(2026, 3, 25, 11, 0, 0, tzinfo=_TZ)
        result = parse_callback_time("this afternoon", TZ, now=now)
        assert result.astimezone(_TZ).day == 25
        assert result.astimezone(_TZ).hour == 14

    def test_this_afternoon_after_target(self):
        """'this afternoon' at 4 PM → now + 1 hour."""
        now = datetime(2026, 3, 25, 16, 0, 0, tzinfo=_TZ)
        result = parse_callback_time("this afternoon", TZ, now=now)
        local = result.astimezone(_TZ)
        assert local.day == 25
        assert local.hour == 17

    def test_this_evening_before_6pm(self):
        """'this evening' at 2 PM → same day 18:00."""
        now = datetime(2026, 3, 25, 14, 0, 0, tzinfo=_TZ)
        result = parse_callback_time("this evening", TZ, now=now)
        assert result.astimezone(_TZ).hour == 18


# ---------------------------------------------------------------------------
# Regression: existing parsing still works
# ---------------------------------------------------------------------------


class TestRegressions:

    def test_tomorrow_at_11am(self):
        now = _make_now()
        result = parse_callback_time("tomorrow at 11 AM", TZ, now=now)
        local = result.astimezone(_TZ)
        assert local.day == 26
        assert local.hour == 11

    def test_in_2_hours(self):
        now = _make_now(hour=14)
        result = parse_callback_time("in 2 hours", TZ, now=now)
        local = result.astimezone(_TZ)
        assert local.hour == 16

    def test_3pm_before_time(self):
        """'3 PM' when it's 1 PM → today at 15:00."""
        now = datetime(2026, 3, 25, 13, 0, 0, tzinfo=_TZ)
        result = parse_callback_time("3 PM", TZ, now=now)
        local = result.astimezone(_TZ)
        assert local.day == 25
        assert local.hour == 15

    def test_3pm_after_time(self):
        """'3 PM' when it's 4 PM → tomorrow at 15:00."""
        now = datetime(2026, 3, 25, 16, 0, 0, tzinfo=_TZ)
        result = parse_callback_time("3 PM", TZ, now=now)
        local = result.astimezone(_TZ)
        assert local.day == 26
        assert local.hour == 15

    def test_none_input_default_delay(self):
        now = _make_now(hour=14)
        result = parse_callback_time(None, TZ, now=now)
        delta = result - now
        assert abs(delta.total_seconds() - 7200) < 60  # ~2 hours

    def test_empty_string_default_delay(self):
        now = _make_now(hour=14)
        result = parse_callback_time("", TZ, now=now)
        delta = result - now
        assert abs(delta.total_seconds() - 7200) < 60

    def test_gibberish_fallback(self):
        now = _make_now(hour=14)
        result = parse_callback_time("xyz gibberish 123", TZ, now=now)
        delta = result - now
        assert abs(delta.total_seconds() - 7200) < 60


# ---------------------------------------------------------------------------
# Calling window enforcement
# ---------------------------------------------------------------------------


class TestCallingWindow:

    def test_within_window_kept(self):
        scheduled = datetime(2026, 3, 30, 10, 0, 0, tzinfo=_TZ)
        result = enforce_calling_window(scheduled, TZ, 9, 20)
        assert result == scheduled

    def test_late_night_pushed_to_next_morning(self):
        """11 PM → next day 9 AM."""
        scheduled = datetime(2026, 3, 30, 23, 0, 0, tzinfo=_TZ)
        result = enforce_calling_window(scheduled, TZ, 9, 20)
        local = result.astimezone(_TZ)
        assert local.day == 31
        assert local.hour == 9

    def test_early_morning_pushed_to_window_start(self):
        """6 AM → same day 9 AM."""
        scheduled = datetime(2026, 3, 30, 6, 0, 0, tzinfo=_TZ)
        result = enforce_calling_window(scheduled, TZ, 9, 20)
        local = result.astimezone(_TZ)
        assert local.day == 30
        assert local.hour == 9
