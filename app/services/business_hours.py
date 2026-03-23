"""Business hours checking and next-available-window calculation.

Used by the sequence scheduler and flow engine to defer actions
outside configured working hours.
"""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def is_within_business_hours(dt: datetime, config: dict) -> bool:
    """Check if a datetime falls within the configured business hours.

    Args:
        dt: The datetime to check (must be timezone-aware).
        config: Business hours config with keys:
            enabled (bool), start (str "HH:MM"), end (str "HH:MM"),
            days (list of day names), timezone (str).

    Returns True if config is disabled or dt is within hours.
    """
    if not config or not config.get("enabled", False):
        return True

    tz = ZoneInfo(config["timezone"])
    local_dt = dt.astimezone(tz)

    # Check day of week
    day_name = DAY_NAMES[local_dt.weekday()]
    if day_name not in config.get("days", []):
        return False

    # Check time range
    start_h, start_m = map(int, config["start"].split(":"))
    end_h, end_m = map(int, config["end"].split(":"))
    start = time(start_h, start_m)
    end = time(end_h, end_m)

    current_time = local_dt.time()
    return start <= current_time < end


def next_available_time(dt: datetime, config: dict) -> datetime:
    """Find the next datetime within business hours.

    If already within hours, returns dt unchanged.
    Otherwise, returns the start of the next available window.
    """
    if not config or not config.get("enabled", False):
        return dt

    if is_within_business_hours(dt, config):
        return dt

    tz = ZoneInfo(config["timezone"])
    local_dt = dt.astimezone(tz)

    start_h, start_m = map(int, config["start"].split(":"))

    # Try today first (if before start time on a valid day), then next 7 days
    for days_ahead in range(0, 8):
        candidate = local_dt.replace(
            hour=start_h, minute=start_m, second=0, microsecond=0
        ) + timedelta(days=days_ahead)

        # Skip if candidate is in the past (same day, already past start)
        if candidate <= local_dt:
            continue

        day_name = DAY_NAMES[candidate.weekday()]
        if day_name in config.get("days", []):
            return candidate

    # Fallback -- should not happen with valid config
    return dt
