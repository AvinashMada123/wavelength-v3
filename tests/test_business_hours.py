import pytest
from datetime import datetime
from zoneinfo import ZoneInfo


def test_is_within_hours_true():
    from app.services.business_hours import is_within_business_hours

    config = {
        "enabled": True,
        "start": "09:00",
        "end": "19:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "timezone": "Asia/Kolkata",
    }
    # Wednesday 2pm IST
    dt = datetime(2026, 3, 25, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_within_business_hours(dt, config) is True


def test_is_within_hours_false_too_early():
    from app.services.business_hours import is_within_business_hours

    config = {
        "enabled": True,
        "start": "09:00",
        "end": "19:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "timezone": "Asia/Kolkata",
    }
    # Wednesday 3am IST
    dt = datetime(2026, 3, 25, 3, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_within_business_hours(dt, config) is False


def test_is_within_hours_false_sunday():
    from app.services.business_hours import is_within_business_hours

    config = {
        "enabled": True,
        "start": "09:00",
        "end": "19:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "timezone": "Asia/Kolkata",
    }
    # Sunday 2pm IST
    dt = datetime(2026, 3, 29, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_within_business_hours(dt, config) is False


def test_disabled_always_returns_true():
    from app.services.business_hours import is_within_business_hours

    config = {"enabled": False}
    dt = datetime(2026, 3, 29, 3, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert is_within_business_hours(dt, config) is True


def test_next_available_window_weekend():
    from app.services.business_hours import next_available_time

    config = {
        "enabled": True,
        "start": "09:00",
        "end": "19:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "timezone": "Asia/Kolkata",
    }
    # Saturday 8pm IST -> next is Monday 9am IST
    dt = datetime(2026, 3, 28, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = next_available_time(dt, config)
    assert result.weekday() == 0  # Monday
    assert result.hour == 9
    assert result.minute == 0


def test_next_available_window_same_day_before_start():
    from app.services.business_hours import next_available_time

    config = {
        "enabled": True,
        "start": "09:00",
        "end": "19:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "timezone": "Asia/Kolkata",
    }
    # Wednesday 7am IST (before 9am start) -> should return Wednesday 9am, NOT Thursday
    dt = datetime(2026, 3, 25, 7, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = next_available_time(dt, config)
    assert result.weekday() == 2  # Wednesday (same day)
    assert result.hour == 9
    assert result.minute == 0
