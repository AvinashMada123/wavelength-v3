"""Smart retry scheduling — computes when to schedule retry calls.

Isolated from queue_processor for testability. All timezone math lives here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def compute_scheduled_at(step: dict, bot_config, *, _now_utc: datetime | None = None) -> datetime:
    """Compute UTC datetime for a retry based on step config.

    For delay_hours: base = now + delay. If preferred_window is set and
    base lands outside it, snap forward to next window opening. delay_hours
    is a MINIMUM delay when combined with preferred_window.

    For next_day: find the next occurrence (in bot timezone) where the
    preferred_window start hasn't passed. If no preferred_window, use
    tomorrow same time.

    Final guardrail: clamp to bot's global callback_window.
    """
    tz = ZoneInfo(getattr(bot_config, "callback_timezone", None) or "Asia/Kolkata")
    now_utc = _now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    window = step.get("preferred_window")

    # --- Step 1: Compute base time ---
    if step.get("delay_hours") is not None:
        base = now_utc + timedelta(hours=step["delay_hours"])
    elif step.get("delay_type") == "next_day":
        if window:
            target_hour = window[0]
            candidate = now_local.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            if candidate <= now_local:
                candidate += timedelta(days=1)
            base = candidate.astimezone(timezone.utc)
        else:
            base = now_utc + timedelta(days=1)
    else:
        # Fallback: 3 hours
        base = now_utc + timedelta(hours=3)

    # --- Step 2: Snap to preferred_window (delay_hours path only) ---
    if window and step.get("delay_hours") is not None:
        base_local = base.astimezone(tz)
        start_h, end_h = window
        if not (start_h <= base_local.hour < end_h):
            candidate = base_local.replace(
                hour=start_h, minute=0, second=0, microsecond=0
            )
            if candidate <= base_local:
                candidate += timedelta(days=1)
            base = candidate.astimezone(timezone.utc)

    # --- Step 3: Global calling-window guardrail ---
    window_start = getattr(bot_config, "callback_window_start", 9)
    window_end = getattr(bot_config, "callback_window_end", 20)
    base_local = base.astimezone(tz)
    if not (window_start <= base_local.hour < window_end):
        candidate = base_local.replace(
            hour=window_start, minute=0, second=0, microsecond=0
        )
        if candidate <= base_local:
            candidate += timedelta(days=1)
        base = candidate.astimezone(timezone.utc)

    return base
