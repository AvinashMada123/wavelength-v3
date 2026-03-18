import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))


def test_calculate_scheduled_time_relative_to_signup():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_signup",
        timing_value={"hours": 1},
        signup_time=signup,
        event_date=None,
        prev_scheduled=None,
    )
    assert result == signup + timedelta(hours=1)


def test_calculate_scheduled_time_relative_to_event():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    event = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_event",
        timing_value={"days": -1, "time": "18:30"},
        signup_time=signup,
        event_date=event,
        prev_scheduled=None,
    )
    assert result.day == 21
    assert result.hour == 18
    assert result.minute == 30


def test_calculate_scheduled_time_relative_to_previous():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    prev = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_previous_step",
        timing_value={"hours": 24},
        signup_time=signup,
        event_date=None,
        prev_scheduled=prev,
    )
    assert result == prev + timedelta(hours=24)


def test_evaluate_skip_conditions_match():
    from app.services.sequence_engine import _should_skip

    conditions = {"field": "attended_saturday", "equals": "yes"}
    context = {"attended_saturday": "yes"}
    assert _should_skip(conditions, context) is True


def test_evaluate_skip_conditions_no_match():
    from app.services.sequence_engine import _should_skip

    conditions = {"field": "attended_saturday", "equals": "yes"}
    context = {"attended_saturday": "no"}
    assert _should_skip(conditions, context) is False


def test_evaluate_skip_conditions_none():
    from app.services.sequence_engine import _should_skip

    assert _should_skip(None, {"any": "data"}) is False


def test_trigger_conditions_match():
    from app.services.sequence_engine import _matches_trigger_conditions

    conditions = {"goal_outcome": ["qualified", "interested"], "min_interest": "medium"}
    analysis = SimpleNamespace(
        goal_outcome="qualified",
        interest_level="high",
        captured_data={},
    )
    assert _matches_trigger_conditions(conditions, analysis) is True


def test_trigger_conditions_no_match():
    from app.services.sequence_engine import _matches_trigger_conditions

    conditions = {"goal_outcome": ["qualified"]}
    analysis = SimpleNamespace(goal_outcome="not_interested", interest_level="low", captured_data={})
    assert _matches_trigger_conditions(conditions, analysis) is False
