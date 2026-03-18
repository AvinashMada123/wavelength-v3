"""Schedule callback calls with time parsing and calling window enforcement."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_queue import QueuedCall

logger = structlog.get_logger(__name__)


def parse_callback_time(
    time_str: str | None,
    tz_name: str = "Asia/Kolkata",
    default_delay_hours: float = 2.0,
) -> datetime:
    """Parse a natural language time string into an absolute datetime.

    Falls back to now + default_delay_hours if time_str is None or unparseable.
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    if not time_str or not time_str.strip():
        return now + timedelta(hours=default_delay_hours)

    text = time_str.strip().lower()

    # Relative: "in X hours/minutes"
    rel_match = re.match(r"in\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)", text)
    if rel_match:
        amount = float(rel_match.group(1))
        unit = rel_match.group(2)
        if unit.startswith("min"):
            return now + timedelta(minutes=amount)
        return now + timedelta(hours=amount)

    # Relative: "after X hours/minutes"
    rel_match2 = re.match(r"after\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)", text)
    if rel_match2:
        amount = float(rel_match2.group(1))
        unit = rel_match2.group(2)
        if unit.startswith("min"):
            return now + timedelta(minutes=amount)
        return now + timedelta(hours=amount)

    # "tomorrow morning/afternoon/evening"
    if "tomorrow" in text:
        tomorrow = now + timedelta(days=1)
        if "morning" in text:
            return tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        if "afternoon" in text:
            return tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        if "evening" in text:
            return tomorrow.replace(hour=18, minute=0, second=0, microsecond=0)
        return tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

    # Try dateutil for specific times like "3 PM", "15:00", "3:30 PM"
    try:
        from dateutil import parser as dateutil_parser
        parsed = dateutil_parser.parse(text, dayfirst=True, fuzzy=True)
        # Apply timezone and set date to today (or tomorrow if time already passed)
        result = now.replace(
            hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
        )
        if result <= now:
            result += timedelta(days=1)
        return result
    except (ValueError, OverflowError):
        pass

    # Fallback: default delay
    logger.warning("callback_time_unparseable", raw=time_str)
    return now + timedelta(hours=default_delay_hours)


def enforce_calling_window(
    scheduled: datetime,
    tz_name: str,
    window_start: int = 9,
    window_end: int = 20,
) -> datetime:
    """Adjust scheduled time to fall within the calling window.

    If the time is outside the window, push to the next window opening.
    """
    tz = ZoneInfo(tz_name)
    local = scheduled.astimezone(tz)

    if window_start <= local.hour < window_end:
        return scheduled  # Already within window

    # Push to next window opening
    if local.hour >= window_end:
        # Past window end — push to next day's start
        next_day = local + timedelta(days=1)
        adjusted = next_day.replace(hour=window_start, minute=0, second=0, microsecond=0)
    else:
        # Before window start — push to today's start
        adjusted = local.replace(hour=window_start, minute=0, second=0, microsecond=0)

    return adjusted.astimezone(timezone.utc)


async def create_scheduled_callback(
    db: AsyncSession,
    org_id,
    bot_id,
    contact_name: str,
    contact_phone: str,
    ghl_contact_id: str | None,
    call_sid: str,
    callback_time: str | None,
    reason: str,
    retry_count: int,
    tz_name: str = "Asia/Kolkata",
    default_delay_hours: float = 2.0,
    window_start: int = 9,
    window_end: int = 20,
) -> QueuedCall:
    """Create a scheduled QueuedCall for a callback.

    Parses the time, enforces calling window, and inserts into queue.
    """
    scheduled = parse_callback_time(callback_time, tz_name, default_delay_hours)
    scheduled = enforce_calling_window(scheduled, tz_name, window_start, window_end)

    # Ensure we store as UTC
    if scheduled.tzinfo is None:
        tz = ZoneInfo(tz_name)
        scheduled = scheduled.replace(tzinfo=tz)
    scheduled_utc = scheduled.astimezone(timezone.utc)

    queued_call = QueuedCall(
        org_id=org_id,
        bot_id=bot_id,
        contact_name=contact_name,
        contact_phone=contact_phone,
        ghl_contact_id=ghl_contact_id,
        source="callback",
        status="queued",
        priority=1,  # Higher priority than normal queued calls
        scheduled_at=scheduled_utc,
        retry_count=retry_count,
        original_call_sid=call_sid,
        extra_vars={
            "callback_reason": reason,
            "original_call_sid": call_sid,
            "retry_count": retry_count,
        },
    )
    db.add(queued_call)
    await db.flush()

    logger.info(
        "callback_scheduled",
        call_sid=call_sid,
        scheduled_at=scheduled_utc.isoformat(),
        retry_count=retry_count,
        reason=reason,
        raw_time=callback_time,
    )

    return queued_call
