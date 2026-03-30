"""Schedule callback calls with time parsing and calling window enforcement."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_queue import QueuedCall
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

# Day-of-week name → weekday int (Monday=0)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Time-of-day keywords → hour
_TOD = {"morning": 10, "afternoon": 14, "evening": 18}

_DEFAULT_HOUR = 10  # Used when only a day is specified


def _parse_hour_ampm(hour: int, ampm: str) -> int:
    """Convert hour + am/pm to 24-hour format."""
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour


def _extract_tod(text: str) -> int | None:
    """Extract time-of-day hour from text, or None."""
    for keyword, hour in _TOD.items():
        if keyword in text:
            return hour

    # Try "at X PM/AM" or "at X:MM PM/AM" pattern
    at_match = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
    if at_match:
        hour = int(at_match.group(1))
        ampm = (at_match.group(3) or "").lower()
        hour = _parse_hour_ampm(hour, ampm)
        if 0 <= hour <= 23:
            return hour

    return None


def _next_weekday(now: datetime, target_weekday: int) -> datetime:
    """Return next occurrence of target_weekday. If today == target, push to next week."""
    days_ahead = target_weekday - now.weekday()
    if days_ahead <= 0:  # Target day is today or already passed this week
        days_ahead += 7
    return now + timedelta(days=days_ahead)


def parse_callback_time(
    time_str: str | None,
    tz_name: str = "Asia/Kolkata",
    default_delay_hours: float = 2.0,
    now: datetime | None = None,
) -> datetime:
    """Parse a natural language time string into an absolute datetime.

    Falls back to now + default_delay_hours if time_str is None or unparseable.
    """
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(tz)

    if not time_str or not time_str.strip():
        return now + timedelta(hours=default_delay_hours)

    text = time_str.strip().lower()

    # --- 1. Relative hours/minutes: "in X hours", "after X minutes" ---
    rel_match = re.match(
        r"(?:in|after)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)", text
    )
    if rel_match:
        amount = float(rel_match.group(1))
        unit = rel_match.group(2)
        if unit.startswith("min"):
            return now + timedelta(minutes=amount)
        return now + timedelta(hours=amount)

    # --- 2. "tomorrow [TOD]" / "tomorrow at X" ---
    if text.startswith("tomorrow"):
        tomorrow = now + timedelta(days=1)
        tod = _extract_tod(text)
        hour = tod if tod is not None else _DEFAULT_HOUR
        return tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0)

    # --- 3. "day after tomorrow [TOD]" ---
    if "day after tomorrow" in text:
        day = now + timedelta(days=2)
        tod = _extract_tod(text)
        hour = tod if tod is not None else _DEFAULT_HOUR
        return day.replace(hour=hour, minute=0, second=0, microsecond=0)

    # --- 4. "this afternoon/evening" ---
    this_match = re.match(r"this\s+(afternoon|evening)", text)
    if this_match:
        target_hour = _TOD[this_match.group(1)]
        result = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if result <= now:
            # Already past that time — schedule 1 hour from now
            result = now + timedelta(hours=1)
            result = result.replace(minute=0, second=0, microsecond=0)
        return result

    # --- 5. "next week" → next Monday ---
    if "next week" in text:
        next_monday = _next_weekday(now, 0)
        tod = _extract_tod(text)
        hour = tod if tod is not None else _DEFAULT_HOUR
        return next_monday.replace(hour=hour, minute=0, second=0, microsecond=0)

    # --- 6. "in a couple of days" / "in a few days" ---
    if "couple of days" in text or "couple days" in text:
        day = now + timedelta(days=2)
        return day.replace(hour=_DEFAULT_HOUR, minute=0, second=0, microsecond=0)
    if "few days" in text:
        day = now + timedelta(days=3)
        return day.replace(hour=_DEFAULT_HOUR, minute=0, second=0, microsecond=0)

    # --- 7. Day-of-week: "monday", "on friday", "next wednesday" ---
    cleaned = re.sub(r"^(on|next)\s+", "", text)
    for day_name, weekday_int in _WEEKDAYS.items():
        if cleaned.startswith(day_name) or cleaned == day_name:
            target_day = _next_weekday(now, weekday_int)
            tod = _extract_tod(text)
            hour = tod if tod is not None else _DEFAULT_HOUR
            result = target_day.replace(hour=hour, minute=0, second=0, microsecond=0)
            return result

    # --- 8. Specific time: "3 PM", "15:00", "3:30 PM" (no dateutil) ---
    time_match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text, re.IGNORECASE)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "").lower()
        hour = _parse_hour_ampm(hour, ampm)
        if 0 <= hour <= 23:
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result <= now:
                result += timedelta(days=1)
            return result

    # --- 9. Fallback: default delay ---
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

    # Pull saved lead custom_fields so callbacks retain all original context
    # (event_name, location, etc.) from the initial GHL trigger
    callback_vars: dict = {}
    try:
        from sqlalchemy import select
        result = await db.execute(
            select(Lead).where(Lead.org_id == org_id, Lead.phone_number == contact_phone)
        )
        lead = result.scalar_one_or_none()
        if lead and lead.custom_fields:
            callback_vars.update(lead.custom_fields)
    except Exception:
        pass  # Non-fatal — proceed without lead vars
    callback_vars.update(
        callback_reason=reason,
        original_call_sid=call_sid,
        retry_count=retry_count,
    )

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
        extra_vars=callback_vars,
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
