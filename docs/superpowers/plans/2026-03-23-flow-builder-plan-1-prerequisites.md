# Flow Builder Plan 1: Prerequisites

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 5 infrastructure pieces required before the flow engine: call outcome feedback loop, Plivo status granularity, business hours system, persistent rate limiting, and AI model routing.

**Architecture:** Each prerequisite is independent and can be built/tested in isolation. They extend existing services (plivo routes, sequence scheduler, anthropic client) and models (organization, call_queue). No new tables yet — those come in Plan 2.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy (async), Anthropic SDK, Google GenAI (Vertex AI), pytest

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §2.1–2.5

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `app/plivo/routes.py` | Fix `_map_plivo_status()` granularity, add touchpoint update in `plivo_event()` |
| Modify | `app/services/sequence_engine.py` | Import and use new status enum |
| Modify | `app/services/sequence_scheduler.py` | Replace in-memory rate limiting with persistent check, add business hours check |
| Modify | `app/models/organization.py` | Add `business_hours` to settings schema |
| Create | `app/services/ai_router.py` | Unified AI generation router (Anthropic + Google GenAI) |
| Modify | `app/services/anthropic_client.py` | Update MODEL_MAP with latest model IDs |
| Create | `app/services/rate_limiter.py` | Persistent per-lead rate limiting service |
| Create | `tests/test_plivo_status.py` | Tests for status mapping + touchpoint feedback |
| Create | `tests/test_rate_limiter.py` | Tests for persistent rate limiting |
| Create | `tests/test_ai_router.py` | Tests for model routing |
| Create | `tests/test_business_hours.py` | Tests for business hours logic |

---

## Task 1: Plivo Status Granularity

**Files:**
- Modify: `app/plivo/routes.py:299-310` (the `_map_plivo_status()` function)
- Create: `tests/test_plivo_status.py`

- [ ] **Step 1: Write failing tests for granular status mapping**

```python
# tests/test_plivo_status.py
import pytest


def test_map_plivo_status_preserves_busy():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("busy") == "busy"


def test_map_plivo_status_preserves_timeout():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("timeout") == "timeout"


def test_map_plivo_status_preserves_no_answer():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("no-answer") == "no_answer"


def test_map_plivo_status_completed_maps_to_picked_up():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("completed") == "picked_up"


def test_map_plivo_status_machine_maps_to_voicemail():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("machine") == "voicemail"


def test_map_plivo_status_cancel_maps_to_failed():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("cancel") == "failed"


def test_map_plivo_status_failed_stays_failed():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("failed") == "failed"


def test_map_plivo_status_unknown_returns_unknown():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status("some_new_status") == "unknown"


def test_map_plivo_status_none_returns_unknown():
    from app.plivo.routes import _map_plivo_status
    assert _map_plivo_status(None) == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plivo_status.py -v`
Expected: `test_map_plivo_status_preserves_busy` FAILS (currently returns "no_answer"), `test_map_plivo_status_completed_maps_to_picked_up` FAILS (currently returns "completed")

- [ ] **Step 3: Update `_map_plivo_status()` with granular mapping**

Replace the function at `app/plivo/routes.py:299-310`:

```python
# Maps raw Plivo CallStatus to normalized CallOutcome enum values.
# IMPORTANT: Do NOT collapse statuses — each value is used for flow branching.
PLIVO_STATUS_MAP = {
    "completed": "picked_up",
    "busy": "busy",
    "failed": "failed",
    "timeout": "timeout",
    "no-answer": "no_answer",
    "cancel": "failed",
    "machine": "voicemail",
}


def _map_plivo_status(plivo_status: str | None) -> str:
    """Map raw Plivo status to normalized CallOutcome.

    Returns the normalized status for flow condition branching.
    Unknown statuses return 'unknown' rather than passing through raw values.
    """
    if plivo_status is None:
        return "unknown"
    return PLIVO_STATUS_MAP.get(plivo_status, "unknown")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_plivo_status.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Update downstream code that uses mapped status values**

Search for all call sites:
Run: `grep -rn "_map_plivo_status\|== \"completed\"\|== \"no_answer\"" app/plivo/routes.py`

The key changes that break downstream logic:
1. `"completed"` is now `"picked_up"` — update any `== "completed"` checks
2. `"busy"` and `"timeout"` no longer map to `"no_answer"` — auto-retry logic at line ~784 currently checks `if mapped_status == "no_answer"` to trigger retries. Update this to also handle `"busy"` and `"timeout"`:

```python
# In plivo_event(), update the auto-retry condition (~line 784):
# OLD: if mapped_status == "no_answer":
# NEW:
RETRIABLE_STATUSES = {"no_answer", "busy", "timeout"}
if mapped_status in RETRIABLE_STATUSES:
```

Also update any `== "completed"` checks to `== "picked_up"`.

- [ ] **Step 5b: Store raw + normalized status on CallLog**

Per spec §2.2, store both values on the CallLog record (not just the touchpoint):

```python
# In plivo_event(), after mapping status, also store raw value:
call_log.status = mapped_status  # normalized (already done)
call_log.raw_plivo_status = plivo_status  # add this raw value
```

Note: This requires adding a `raw_plivo_status` column to `CallLog`. Add to the migration in Task 3.

- [ ] **Step 6: Commit**

```bash
git add app/plivo/routes.py tests/test_plivo_status.py
git commit -m "fix: preserve granular Plivo call statuses for flow branching

Previously busy/timeout/no-answer all collapsed to 'no_answer'.
Now each maps to a distinct value: busy, timeout, no_answer, picked_up,
voicemail, failed, unknown. Needed for flow builder condition nodes."
```

---

## Task 2: Call Outcome Feedback Loop

**Files:**
- Modify: `app/plivo/routes.py:720+` (the `plivo_event()` function)
- Modify: `app/services/sequence_engine.py` (add touchpoint update helper)
- Create: `tests/test_plivo_status.py` (add to existing)

- [ ] **Step 1: Write failing test for touchpoint update on call completion**

Add to `tests/test_plivo_status.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_update_touchpoint_on_call_outcome():
    """When plivo_event fires, it should update the sequence touchpoint status."""
    from app.plivo.routes import _update_sequence_touchpoint

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = MagicMock(
        id="tp-123",
        status="scheduled",
    )
    mock_db.execute.return_value = mock_result

    await _update_sequence_touchpoint(
        db=mock_db,
        touchpoint_id="tp-123",
        call_outcome="picked_up",
        raw_plivo_status="completed",
    )

    # Verify the touchpoint was updated
    mock_db.execute.assert_called()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_touchpoint_skips_if_not_found():
    """Should not error if touchpoint ID doesn't exist."""
    from app.plivo.routes import _update_sequence_touchpoint

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    # Should not raise
    await _update_sequence_touchpoint(
        db=mock_db,
        touchpoint_id="nonexistent",
        call_outcome="picked_up",
        raw_plivo_status="completed",
    )

    mock_db.commit.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plivo_status.py::test_update_touchpoint_on_call_outcome -v`
Expected: FAIL — `_update_sequence_touchpoint` does not exist yet

- [ ] **Step 3: Implement `_update_sequence_touchpoint` in routes.py**

Add this function in `app/plivo/routes.py` (before `plivo_event`):

```python
async def _update_sequence_touchpoint(
    db,
    touchpoint_id: str,
    call_outcome: str,
    raw_plivo_status: str,
) -> None:
    """Update a sequence touchpoint with the call outcome.

    Called from plivo_event() when a call finishes and the QueuedCall
    has a sequence_touchpoint_id in extra_vars.
    """
    from app.models.sequence import SequenceTouchpoint
    from sqlalchemy import select

    result = await db.execute(
        select(SequenceTouchpoint).where(SequenceTouchpoint.id == touchpoint_id)
    )
    touchpoint = result.scalars().first()

    if not touchpoint:
        logger.warning(f"Touchpoint {touchpoint_id} not found for call outcome update")
        return

    if touchpoint.status not in ("scheduled", "sending"):
        logger.info(f"Touchpoint {touchpoint_id} already in terminal state: {touchpoint.status}")
        return

    # Update touchpoint with call outcome
    touchpoint.status = "sent" if call_outcome == "picked_up" else "failed"
    touchpoint.sent_at = datetime.utcnow()

    # Store outcome in step_snapshot for downstream access
    snapshot = touchpoint.step_snapshot or {}
    snapshot["call_outcome"] = call_outcome
    snapshot["raw_plivo_status"] = raw_plivo_status
    touchpoint.step_snapshot = snapshot

    await db.commit()
    logger.info(f"Updated touchpoint {touchpoint_id} with call outcome: {call_outcome}")
```

- [ ] **Step 4: Wire `_update_sequence_touchpoint` into `plivo_event()`**

In `app/plivo/routes.py`, inside the `plivo_event()` function (around line 728, after status mapping), add:

```python
    # --- Call outcome feedback loop for sequences ---
    # Check if this call was triggered by a sequence touchpoint
    if queued_call and queued_call.extra_vars:
        touchpoint_id = queued_call.extra_vars.get("sequence_touchpoint_id")
        if touchpoint_id:
            await _update_sequence_touchpoint(
                db=db,
                touchpoint_id=touchpoint_id,
                call_outcome=mapped_status,
                raw_plivo_status=plivo_status,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_plivo_status.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/plivo/routes.py tests/test_plivo_status.py
git commit -m "feat: close call outcome feedback loop for sequence touchpoints

When plivo_event() fires after a call ends, check QueuedCall.extra_vars
for sequence_touchpoint_id and update the touchpoint with the call outcome
(picked_up/no_answer/busy/timeout/failed/voicemail). This is the foundation
for flow builder condition branching on call outcomes."
```

---

## Task 3: Persistent Rate Limiting

**Files:**
- Create: `app/services/rate_limiter.py`
- Modify: `app/services/sequence_scheduler.py:86-107`
- Create: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests for rate limiter**

```python
# tests/test_rate_limiter.py
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_can_contact_allows_first_contact():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # No prior contacts
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result

    limiter = RateLimiter(db=mock_db)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is True


@pytest.mark.asyncio
async def test_can_contact_blocks_when_daily_cap_reached():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # 5 contacts today (at daily cap)
    mock_result = MagicMock()
    mock_result.scalar.return_value = 5
    mock_db.execute.return_value = mock_result

    limiter = RateLimiter(db=mock_db, daily_cap=5)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_can_contact_blocks_when_hourly_cap_reached():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # Simulate: daily OK (3), hourly at cap (2)
    mock_result_daily = MagicMock()
    mock_result_daily.scalar.return_value = 3
    mock_result_hourly = MagicMock()
    mock_result_hourly.scalar.return_value = 2
    mock_db.execute.side_effect = [mock_result_daily, mock_result_hourly]

    limiter = RateLimiter(db=mock_db, daily_cap=5, hourly_cap=2)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_can_contact_blocks_during_cooldown():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # Daily OK (1), hourly OK (1), but last contact was 30s ago (within 60s cooldown)
    mock_result_daily = MagicMock()
    mock_result_daily.scalar.return_value = 1
    mock_result_hourly = MagicMock()
    mock_result_hourly.scalar.return_value = 1
    mock_result_last = MagicMock()
    mock_result_last.scalar.return_value = datetime.utcnow() - timedelta(seconds=30)
    mock_db.execute.side_effect = [mock_result_daily, mock_result_hourly, mock_result_last]

    limiter = RateLimiter(db=mock_db, daily_cap=5, hourly_cap=2, cooldown_seconds=60)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_record_contact_inserts_row():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    limiter = RateLimiter(db=mock_db)

    await limiter.record_contact(lead_id="lead-1", org_id="org-1", channel="whatsapp_template")
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rate_limiter.py -v`
Expected: FAIL — `app.services.rate_limiter` does not exist

- [ ] **Step 3: Implement rate limiter service**

```python
# app/services/rate_limiter.py
"""Persistent per-lead rate limiting for sequence/flow actions.

Replaces the in-memory phone-spacing dict in sequence_scheduler.py.
Uses a lightweight SQL query against a contact log to enforce caps.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Defaults — can be overridden by org settings
DEFAULT_DAILY_CAP = 5
DEFAULT_HOURLY_CAP = 2
DEFAULT_COOLDOWN_SECONDS = 60


class RateLimiter:
    def __init__(
        self,
        db,
        daily_cap: int = DEFAULT_DAILY_CAP,
        hourly_cap: int = DEFAULT_HOURLY_CAP,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self.db = db
        self.daily_cap = daily_cap
        self.hourly_cap = hourly_cap
        self.cooldown_seconds = cooldown_seconds

    async def can_contact(self, lead_id: str, org_id: str) -> bool:
        """Check if we can contact this lead right now.

        Checks daily cap, hourly cap, and cooldown period.
        Returns True if all caps are within limits.
        """
        now = datetime.utcnow()

        # Check daily cap
        daily_count = await self._count_contacts(
            lead_id, org_id, since=now - timedelta(days=1)
        )
        if daily_count >= self.daily_cap:
            logger.debug(f"Lead {lead_id} hit daily cap ({daily_count}/{self.daily_cap})")
            return False

        # Check hourly cap
        hourly_count = await self._count_contacts(
            lead_id, org_id, since=now - timedelta(hours=1)
        )
        if hourly_count >= self.hourly_cap:
            logger.debug(f"Lead {lead_id} hit hourly cap ({hourly_count}/{self.hourly_cap})")
            return False

        # Check cooldown
        last_contact = await self._last_contact_time(lead_id, org_id)
        if last_contact and (now - last_contact).total_seconds() < self.cooldown_seconds:
            logger.debug(f"Lead {lead_id} in cooldown period")
            return False

        return True

    async def record_contact(
        self, lead_id: str, org_id: str, channel: str
    ) -> None:
        """Record that we contacted a lead. Called after successful send."""
        await self.db.execute(
            text(
                "INSERT INTO lead_contact_log (lead_id, org_id, channel, contacted_at) "
                "VALUES (:lead_id, :org_id, :channel, :contacted_at)"
            ),
            {
                "lead_id": lead_id,
                "org_id": org_id,
                "channel": channel,
                "contacted_at": datetime.utcnow(),
            },
        )
        await self.db.commit()

    async def _count_contacts(
        self, lead_id: str, org_id: str, since: datetime
    ) -> int:
        result = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM lead_contact_log "
                "WHERE lead_id = :lead_id AND org_id = :org_id AND contacted_at >= :since"
            ),
            {"lead_id": lead_id, "org_id": org_id, "since": since},
        )
        return result.scalar() or 0

    async def _last_contact_time(
        self, lead_id: str, org_id: str
    ) -> datetime | None:
        result = await self.db.execute(
            text(
                "SELECT MAX(contacted_at) FROM lead_contact_log "
                "WHERE lead_id = :lead_id AND org_id = :org_id"
            ),
            {"lead_id": lead_id, "org_id": org_id},
        )
        return result.scalar()
```

- [ ] **Step 4: Create the database migration**

Run: `alembic revision --autogenerate -m "add lead_contact_log and raw_plivo_status"`

If the project uses raw SQL migrations, create a migration file at `migrations/` (check existing pattern). The migration should contain:

```sql
-- lead_contact_log for persistent rate limiting
CREATE TABLE lead_contact_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL,
    org_id UUID NOT NULL,
    channel VARCHAR(50) NOT NULL,
    contacted_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lead_contact_log_lookup
    ON lead_contact_log (lead_id, org_id, contacted_at DESC);

-- raw_plivo_status on call_logs (per spec §2.2)
ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS raw_plivo_status VARCHAR(50);
```

Run: `alembic upgrade head` (or equivalent migration command for this project)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_rate_limiter.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Wire rate limiter into sequence_scheduler.py**

In `app/services/sequence_scheduler.py`, replace the in-memory `_recent_phones` dict (lines 86-107) with the persistent rate limiter:

```python
# Replace the in-memory phone spacing with persistent rate limiter
from app.services.rate_limiter import RateLimiter

# Inside _process_batch(), before processing each touchpoint:
limiter = RateLimiter(db=db)
if not await limiter.can_contact(lead_id=str(tp.lead_id), org_id=str(tp.org_id)):
    logger.debug(f"Skipping touchpoint {tp.id} — rate limit hit for lead {tp.lead_id}")
    continue

# After successful send, record the contact:
await limiter.record_contact(
    lead_id=str(tp.lead_id),
    org_id=str(tp.org_id),
    channel=tp.step_snapshot.get("channel", "unknown"),
)
```

Remove the `_recent_phones` dict and all references to it.

- [ ] **Step 7: Commit**

```bash
git add app/services/rate_limiter.py tests/test_rate_limiter.py app/services/sequence_scheduler.py
git commit -m "feat: add persistent per-lead rate limiting

Replace in-memory phone spacing with DB-backed rate limiter.
Enforces daily cap (5), hourly cap (2), and 60s cooldown per lead.
Persists across scheduler restarts. Uses lead_contact_log table."
```

---

## Task 4: Business Hours System

**Files:**
- Create: `app/services/business_hours.py`
- Create: `tests/test_business_hours.py`

- [ ] **Step 1: Write failing tests for business hours check**

```python
# tests/test_business_hours.py
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
    # Saturday 8pm IST → next is Monday 9am IST
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
    # Wednesday 7am IST (before 9am start) → should return Wednesday 9am, NOT Thursday
    dt = datetime(2026, 3, 25, 7, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = next_available_time(dt, config)
    assert result.weekday() == 2  # Wednesday (same day)
    assert result.hour == 9
    assert result.minute == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_business_hours.py -v`
Expected: FAIL — `app.services.business_hours` does not exist

- [ ] **Step 3: Implement business hours service**

```python
# app/services/business_hours.py
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

    # Fallback — should not happen with valid config
    return dt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_business_hours.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Add business_hours to Organization settings**

In `app/models/organization.py`, document that the `settings` JSONB field now supports a `business_hours` key:

```python
# In Organization model, add a comment documenting the settings schema:
# settings JSONB schema:
#   {
#     "business_hours": {
#       "enabled": true,
#       "start": "09:00",
#       "end": "19:00",
#       "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
#       "timezone": "Asia/Kolkata"
#     },
#     "rate_limits": {
#       "daily_cap": 5,
#       "hourly_cap": 2,
#       "cooldown_seconds": 60
#     }
#   }
```

No migration needed — `settings` is already a JSONB field. The business hours config is read from `org.settings.get("business_hours", {})` at runtime.

- [ ] **Step 6: Commit**

```bash
git add app/services/business_hours.py tests/test_business_hours.py app/models/organization.py
git commit -m "feat: add business hours checking service

Supports is_within_business_hours() and next_available_time() with
configurable days, time range, and timezone. Org settings JSONB
extended with business_hours and rate_limits keys. Used by scheduler
to defer actions outside working hours."
```

---

## Task 5: AI Model Router

**Files:**
- Create: `app/services/ai_router.py`
- Modify: `app/services/anthropic_client.py:13-16` (update MODEL_MAP)
- Create: `tests/test_ai_router.py`

- [ ] **Step 1: Write failing tests for AI model routing**

```python
# tests/test_ai_router.py
import pytest
from unittest.mock import AsyncMock, patch


def test_resolve_provider_anthropic():
    from app.services.ai_router import resolve_provider
    assert resolve_provider("claude-sonnet-4-6") == "anthropic"
    assert resolve_provider("claude-haiku-4-5") == "anthropic"


def test_resolve_provider_google():
    from app.services.ai_router import resolve_provider
    assert resolve_provider("gemini-2.5-flash") == "google"
    assert resolve_provider("gemini-2.5-pro") == "google"
    assert resolve_provider("gemini-2.0-flash") == "google"


def test_resolve_provider_unknown_raises():
    from app.services.ai_router import resolve_provider
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_provider("gpt-4o")


@pytest.mark.asyncio
async def test_generate_routes_to_anthropic():
    from app.services.ai_router import generate_content

    with patch("app.services.ai_router.anthropic_client") as mock_anthropic:
        mock_anthropic.generate_content = AsyncMock(return_value="Hello from Claude")

        result = await generate_content(
            prompt="Say hello to {{name}}",
            variables={"name": "Animesh"},
            model="claude-sonnet-4-6",
        )

        assert result == "Hello from Claude"
        mock_anthropic.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_generate_routes_to_google():
    from app.services.ai_router import generate_content

    with patch("app.services.ai_router._generate_with_google", new_callable=AsyncMock) as mock_google:
        mock_google.return_value = "Hello from Gemini"

        result = await generate_content(
            prompt="Say hello to {{name}}",
            variables={"name": "Animesh"},
            model="gemini-2.5-flash",
        )

        assert result == "Hello from Gemini"
        mock_google.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_router.py -v`
Expected: FAIL — `app.services.ai_router` does not exist

- [ ] **Step 3: Implement AI model router**

```python
# app/services/ai_router.py
"""Unified AI content generation router.

Routes generation requests to Anthropic or Google based on model prefix.
Used by flow engine action nodes for AI-generated content.
"""
import logging
import re

from app.services import anthropic_client

logger = logging.getLogger(__name__)

# Supported models and their providers
SUPPORTED_MODELS = {
    "gemini-2.5-flash": "google",
    "gemini-2.5-pro": "google",
    "gemini-2.0-flash": "google",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5": "anthropic",
}

# Display names for the frontend dropdown
MODEL_DISPLAY_NAMES = {
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-haiku-4-5": "Claude Haiku 4.5",
}

DEFAULT_MODEL = "gemini-2.5-flash"


def resolve_provider(model: str) -> str:
    """Determine which provider handles this model."""
    if model in SUPPORTED_MODELS:
        return SUPPORTED_MODELS[model]
    raise ValueError(f"Unknown model: {model}. Supported: {list(SUPPORTED_MODELS.keys())}")


def _interpolate_variables(prompt: str, variables: dict) -> str:
    """Replace {{var}} placeholders with values from variables dict."""
    def replace_match(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))
    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replace_match, prompt)


async def generate_content(
    prompt: str,
    variables: dict,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    org_id: str | None = None,
    reference: str | None = None,
) -> str:
    """Generate AI content, routing to the correct provider.

    Args:
        prompt: Prompt template with {{variable}} placeholders.
        variables: Dict of variable values to interpolate.
        model: Model ID (e.g., "gemini-2.5-flash", "claude-sonnet-4-6").
        max_tokens: Max output tokens.
        org_id: For billing/tracking.
        reference: Context reference string.

    Returns: Generated text content.
    """
    provider = resolve_provider(model)

    if provider == "anthropic":
        return await anthropic_client.generate_content(
            prompt=prompt,
            variables=variables,
            model=model,
            max_tokens=max_tokens,
            org_id=org_id,
            reference=reference,
        )
    elif provider == "google":
        return await _generate_with_google(
            prompt=prompt,
            variables=variables,
            model=model,
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


async def _generate_with_google(
    prompt: str,
    variables: dict,
    model: str,
    max_tokens: int = 300,
) -> str:
    """Generate content using Google GenAI (Vertex AI).

    Uses the same pattern as call_analyzer.py's _gemini_call().
    """
    from google import genai
    from google.genai.types import GenerateContentConfig
    from app.config import settings

    interpolated_prompt = _interpolate_variables(prompt, variables)

    # Must pass project + location — same pattern as call_analyzer.py
    client = genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.VERTEX_AI_LOCATION,
    )
    response = await client.aio.models.generate_content(
        model=model,
        contents=interpolated_prompt,
        config=GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.7,
        ),
    )

    return response.text
```

- [ ] **Step 4: Update anthropic_client.py MODEL_MAP**

In `app/services/anthropic_client.py:13-16`, update the MODEL_MAP to include the new model IDs:

```python
MODEL_MAP = {
    "claude-sonnet": "claude-sonnet-4-20250514",
    "claude-haiku": "claude-haiku-4-5-20251001",
    # New IDs used by flow builder AI nodes
    "claude-sonnet-4-6": "claude-sonnet-4-20250514",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ai_router.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/ai_router.py app/services/anthropic_client.py tests/test_ai_router.py
git commit -m "feat: add AI model router for multi-provider generation

Unified generate_content() routes to Anthropic (claude-*) or Google
GenAI (gemini-*) based on model prefix. Supports 5 models with
gemini-2.5-flash as default. Used by flow builder AI nodes."
```

---

## Task 6: Integration — Wire Everything Into Scheduler

**Files:**
- Modify: `app/services/sequence_scheduler.py`

- [ ] **Step 1: Read current scheduler implementation**

Read `app/services/sequence_scheduler.py` in full to understand the current `_process_batch()` flow and identify exact insertion points.

- [ ] **Step 2: Add business hours check to scheduler**

In `_process_batch()`, after fetching due touchpoints and before processing each one, add:

```python
from app.services.business_hours import is_within_business_hours, next_available_time
from datetime import datetime
from zoneinfo import ZoneInfo

# Inside the processing loop, before executing the touchpoint:
send_window = tp.step_snapshot.get("send_window")
if send_window:
    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    if not is_within_business_hours(now_utc, send_window):
        # Defer to next available window
        next_time = next_available_time(now_utc, send_window)
        tp.scheduled_at = next_time
        await db.commit()
        logger.info(f"Deferred touchpoint {tp.id} to {next_time} (outside business hours)")
        continue
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/ -v --timeout=30`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add app/services/sequence_scheduler.py
git commit -m "feat: wire business hours and persistent rate limiting into scheduler

Scheduler now checks send_window config before executing touchpoints
and defers to next available business hours window. In-memory phone
spacing replaced with persistent RateLimiter."
```

---

## Summary

| Task | What it does | Files |
|------|-------------|-------|
| 1 | Plivo status granularity | `routes.py`, tests |
| 2 | Call outcome → touchpoint feedback | `routes.py`, `sequence_engine.py`, tests |
| 3 | Persistent rate limiting | `rate_limiter.py`, `sequence_scheduler.py`, migration, tests |
| 4 | Business hours system | `business_hours.py`, tests |
| 5 | AI model router | `ai_router.py`, `anthropic_client.py`, tests |
| 6 | Integration wiring | `sequence_scheduler.py` |

**Total:** 6 tasks, ~30 steps, 6 commits.

After completing this plan, proceed to **Plan 2: Data Model & Flow Engine**.
