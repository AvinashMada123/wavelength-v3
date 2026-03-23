"""Extended tests for sequence engine — pure functions: parse_bot_event_date,
_calculate_scheduled_time edge cases, _should_skip, _matches_trigger_conditions."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.services.sequence_engine import (
    parse_bot_event_date,
    _calculate_scheduled_time,
    _should_skip,
    _matches_trigger_conditions,
)


# ---------------------------------------------------------------------------
# parse_bot_event_date
# ---------------------------------------------------------------------------

class TestParseBotEventDate:
    def test_standard_format_with_ordinal(self):
        result = parse_bot_event_date("7th March 2026")
        assert result is not None
        assert "2026-03-07" in result

    def test_ordinal_st(self):
        result = parse_bot_event_date("1st January 2026")
        assert result is not None
        assert "2026-01-01" in result

    def test_ordinal_nd(self):
        result = parse_bot_event_date("2nd February 2026")
        assert result is not None
        assert "2026-02-02" in result

    def test_ordinal_rd(self):
        result = parse_bot_event_date("3rd March 2026")
        assert result is not None
        assert "2026-03-03" in result

    def test_iso_format(self):
        result = parse_bot_event_date("2026-03-15")
        assert result is not None
        assert "2026-03-15" in result

    def test_dd_mm_yyyy_slash(self):
        result = parse_bot_event_date("15/03/2026")
        assert result is not None
        assert "2026-03-15" in result

    def test_mm_dd_yyyy_slash(self):
        result = parse_bot_event_date("03/15/2026")
        assert result is not None
        # Could be March 15 or 3rd of 15th month (invalid) depending on order
        # The function tries dd/mm/yyyy first, then mm/dd/yyyy

    def test_with_time_12h(self):
        result = parse_bot_event_date("7th March 2026", "7:30 PM")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 19
        assert dt.minute == 30

    def test_with_time_24h(self):
        result = parse_bot_event_date("7th March 2026", "14:00")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 14
        assert dt.minute == 0

    def test_with_time_short_12h(self):
        result = parse_bot_event_date("7th March 2026", "3 PM")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 15

    def test_empty_time_ignored(self):
        result = parse_bot_event_date("7th March 2026", "")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 0
        assert dt.minute == 0

    def test_unparseable_date_returns_none(self):
        assert parse_bot_event_date("not a date") is None

    def test_unparseable_time_ignored(self):
        result = parse_bot_event_date("7th March 2026", "not-a-time")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.hour == 0  # time not applied

    def test_month_day_year_format(self):
        result = parse_bot_event_date("March 15 2026")
        assert result is not None
        assert "2026-03-15" in result

    def test_whitespace_handling(self):
        result = parse_bot_event_date("  7th March 2026  ", "  7:30 PM  ")
        assert result is not None


# ---------------------------------------------------------------------------
# _calculate_scheduled_time — extended edge cases
# ---------------------------------------------------------------------------

class TestCalculateScheduledTimeExtended:
    def test_relative_to_signup_days_and_hours(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_signup",
            {"days": 2, "hours": 3},
            signup, None, None,
        )
        assert result == signup + timedelta(days=2, hours=3)

    def test_relative_to_signup_with_specific_time(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_signup",
            {"days": 1, "time": "09:00"},
            signup, None, None,
        )
        assert result.day == 19
        assert result.hour == 9
        assert result.minute == 0

    def test_relative_to_signup_minutes(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_signup",
            {"minutes": 30},
            signup, None, None,
        )
        assert result == signup + timedelta(minutes=30)

    def test_relative_to_signup_zero_delta(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_signup",
            {},
            signup, None, None,
        )
        assert result == signup

    def test_relative_to_event_no_event_date_raises(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="relative_to_event requires"):
            _calculate_scheduled_time(
                "relative_to_event",
                {"days": -1},
                signup, None, None,
            )

    def test_relative_to_event_negative_days(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        event = datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_event",
            {"days": -3, "time": "10:00"},
            signup, event, None,
        )
        assert result.day == 22
        assert result.hour == 10

    def test_relative_to_event_hours_without_time(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        event = datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_event",
            {"days": 0, "hours": -2},
            signup, event, None,
        )
        assert result == event + timedelta(hours=-2)

    def test_relative_to_previous_no_prev_falls_back_to_signup(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_previous_step",
            {"hours": 2},
            signup, None, None,
        )
        assert result == signup + timedelta(hours=2)

    def test_relative_to_previous_with_time_override(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        prev = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = _calculate_scheduled_time(
            "relative_to_previous_step",
            {"days": 1, "time": "08:00"},
            signup, None, prev,
        )
        assert result.day == 20
        assert result.hour == 8
        assert result.minute == 0

    def test_unknown_timing_type_raises(self):
        signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Unknown timing_type"):
            _calculate_scheduled_time(
                "absolute",
                {},
                signup, None, None,
            )


# ---------------------------------------------------------------------------
# _should_skip — extended edge cases
# ---------------------------------------------------------------------------

class TestShouldSkipExtended:
    def test_none_conditions_returns_false(self):
        assert _should_skip(None, {"any": "data"}) is False

    def test_empty_dict_conditions_returns_false(self):
        assert _should_skip({}, {"any": "data"}) is False

    def test_equals_match(self):
        assert _should_skip({"field": "status", "equals": "done"}, {"status": "done"}) is True

    def test_equals_no_match(self):
        assert _should_skip({"field": "status", "equals": "done"}, {"status": "pending"}) is False

    def test_equals_type_coercion(self):
        """Values are compared as strings."""
        assert _should_skip({"field": "count", "equals": "5"}, {"count": 5}) is True

    def test_not_equals_match_skips(self):
        """not_equals means skip when actual != expected."""
        assert _should_skip({"field": "status", "not_equals": "done"}, {"status": "pending"}) is True

    def test_not_equals_no_skip(self):
        assert _should_skip({"field": "status", "not_equals": "done"}, {"status": "done"}) is False

    def test_missing_field_in_context(self):
        assert _should_skip({"field": "missing", "equals": "x"}, {"other": "y"}) is False

    def test_equals_takes_priority_over_not_equals(self):
        """When both present, equals is checked first."""
        cond = {"field": "status", "equals": "done", "not_equals": "pending"}
        assert _should_skip(cond, {"status": "done"}) is True

    def test_no_equals_or_not_equals_returns_false(self):
        assert _should_skip({"field": "status"}, {"status": "done"}) is False


# ---------------------------------------------------------------------------
# _matches_trigger_conditions — extended edge cases
# ---------------------------------------------------------------------------

class TestMatchesTriggerConditionsExtended:
    def _make_analysis(self, **kwargs):
        defaults = {"goal_outcome": "none", "interest_level": "low", "captured_data": {}}
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_empty_conditions_always_matches(self):
        assert _matches_trigger_conditions({}, self._make_analysis()) is True

    def test_none_conditions_always_matches(self):
        assert _matches_trigger_conditions(None, self._make_analysis()) is True

    def test_goal_outcome_list_match(self):
        conditions = {"goal_outcome": ["confirmed", "tentative"]}
        assert _matches_trigger_conditions(conditions, self._make_analysis(goal_outcome="confirmed")) is True

    def test_goal_outcome_list_no_match(self):
        conditions = {"goal_outcome": ["confirmed"]}
        assert _matches_trigger_conditions(conditions, self._make_analysis(goal_outcome="declined")) is False

    @pytest.mark.parametrize(
        "min_interest,interest_level,expected",
        [
            ("high", "high", True),
            ("high", "medium", False),
            ("high", "low", False),
            ("medium", "high", True),
            ("medium", "medium", True),
            ("medium", "low", False),
            ("low", "low", True),
        ],
        ids=[
            "high_requires_high",
            "high_rejects_medium",
            "high_rejects_low",
            "medium_accepts_high",
            "medium_accepts_medium",
            "medium_rejects_low",
            "low_accepts_low",
        ],
    )
    def test_min_interest(self, min_interest, interest_level, expected):
        conditions = {"min_interest": min_interest}
        assert _matches_trigger_conditions(
            conditions, self._make_analysis(interest_level=interest_level)
        ) is expected

    def test_combined_conditions_both_must_pass(self):
        conditions = {"goal_outcome": ["confirmed"], "min_interest": "medium"}
        # Outcome match, interest too low
        assert _matches_trigger_conditions(
            conditions,
            self._make_analysis(goal_outcome="confirmed", interest_level="low"),
        ) is False
        # Both match
        assert _matches_trigger_conditions(
            conditions,
            self._make_analysis(goal_outcome="confirmed", interest_level="high"),
        ) is True

    def test_missing_interest_level_attribute(self):
        """Analysis without interest_level defaults to low."""
        conditions = {"min_interest": "medium"}
        analysis = SimpleNamespace(goal_outcome="none", captured_data={})
        assert _matches_trigger_conditions(conditions, analysis) is False

    def test_unknown_interest_level(self):
        conditions = {"min_interest": "medium"}
        assert _matches_trigger_conditions(
            conditions,
            self._make_analysis(interest_level="unknown"),
        ) is False
