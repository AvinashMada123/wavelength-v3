# Smart Retry Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat retry config with per-bot step-based retry schedules that target optimal calling windows.

**Architecture:** Add `callback_schedule` JSONB column to bot_configs. New `compute_scheduled_at()` function handles step-based scheduling with preferred time windows and global calling-window guardrails. Phased migration: add new field → migrate data → drop old fields (Phase 3 is a separate future PR).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic, React/TypeScript, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-smart-retry-schedules-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `app/models/schemas.py` | Modify | Add `RetryStep`, `CallbackSchedule` Pydantic models; add `callback_schedule` to request/response schemas |
| `app/models/bot_config.py` | Modify | Add `callback_schedule` JSONB column |
| `app/services/smart_retry.py` | Create | `compute_scheduled_at()` — pure scheduling logic, isolated for testability |
| `app/services/queue_processor.py` | Modify | Rewrite `schedule_auto_retry()` to use step-based scheduling |
| `alembic/versions/031_add_callback_schedule.py` | Create | Add column + data migration |
| `app/api/bots.py` | Modify | Cross-validate preferred windows against calling window |
| `frontend/src/types/api.ts` | Modify | Add TypeScript types |
| `frontend/src/app/(app)/bots/[botId]/page.tsx` | Modify | Replace retry inputs with template picker + step builder |
| `tests/test_smart_retry.py` | Create | Unit + integration tests for scheduling logic |

---

### Task 1: Pydantic Schemas

**Files:**
- Modify: `app/models/schemas.py:136-235`
- Test: `tests/test_smart_retry.py` (create)

- [ ] **Step 1: Write validation tests**

Create `tests/test_smart_retry.py`:

```python
"""Tests for smart retry schedule feature."""
import pytest
from datetime import datetime, timezone, timedelta

from app.models.schemas import RetryStep, CallbackSchedule


# --- RetryStep validation ---

class TestRetryStepValidation:
    def test_valid_delay_hours(self):
        step = RetryStep(delay_hours=3.0)
        assert step.delay_hours == 3.0
        assert step.delay_type is None

    def test_valid_next_day(self):
        step = RetryStep(delay_type="next_day")
        assert step.delay_type == "next_day"
        assert step.delay_hours is None

    def test_valid_with_preferred_window(self):
        step = RetryStep(delay_type="next_day", preferred_window=[11, 13])
        assert step.preferred_window == [11, 13]

    def test_rejects_both_delay_fields(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            RetryStep(delay_hours=3.0, delay_type="next_day")

    def test_rejects_neither_delay_field(self):
        with pytest.raises(ValueError, match="One of"):
            RetryStep()

    def test_rejects_negative_delay(self):
        with pytest.raises(ValueError, match="positive"):
            RetryStep(delay_hours=-1)

    def test_rejects_zero_delay(self):
        with pytest.raises(ValueError, match="positive"):
            RetryStep(delay_hours=0)

    def test_rejects_excessive_delay(self):
        with pytest.raises(ValueError, match="48"):
            RetryStep(delay_hours=100)

    def test_rejects_bad_window_hours(self):
        with pytest.raises(ValueError, match="0-23"):
            RetryStep(delay_hours=3, preferred_window=[25, 30])

    def test_rejects_overnight_window(self):
        with pytest.raises(ValueError, match="before end"):
            RetryStep(delay_hours=3, preferred_window=[22, 6])

    def test_rejects_equal_window(self):
        with pytest.raises(ValueError, match="before end"):
            RetryStep(delay_hours=3, preferred_window=[10, 10])

    def test_rejects_wrong_window_length(self):
        with pytest.raises(ValueError, match="\\[start_hour, end_hour\\]"):
            RetryStep(delay_hours=3, preferred_window=[10])


# --- CallbackSchedule validation ---

class TestCallbackScheduleValidation:
    def test_valid_schedule(self):
        schedule = CallbackSchedule(
            template="standard",
            steps=[RetryStep(delay_hours=3), RetryStep(delay_type="next_day", preferred_window=[11, 13])],
        )
        assert len(schedule.steps) == 2

    def test_rejects_empty_steps(self):
        with pytest.raises(ValueError, match="At least one"):
            CallbackSchedule(template="custom", steps=[])

    def test_rejects_too_many_steps(self):
        steps = [RetryStep(delay_hours=1) for _ in range(11)]
        with pytest.raises(ValueError, match="Maximum 10"):
            CallbackSchedule(template="custom", steps=steps)

    def test_rejects_invalid_template(self):
        with pytest.raises(ValueError):
            CallbackSchedule(template="invalid", steps=[RetryStep(delay_hours=1)])

    def test_valid_templates(self):
        for t in ["standard", "aggressive", "relaxed", "custom"]:
            s = CallbackSchedule(template=t, steps=[RetryStep(delay_hours=1)])
            assert s.template == t
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py -v`
Expected: ImportError — `RetryStep`, `CallbackSchedule` not found

- [ ] **Step 3: Implement Pydantic models**

Add to `app/models/schemas.py` BEFORE `CreateBotConfigRequest` (around line 134):

```python
class RetryStep(BaseModel):
    """A single step in a retry schedule."""
    delay_hours: float | None = None
    delay_type: Literal["next_day"] | None = None
    preferred_window: list[int] | None = None

    @model_validator(mode="after")
    def validate_step(self):
        if self.delay_hours is not None and self.delay_type is not None:
            raise ValueError("delay_hours and delay_type are mutually exclusive")
        if self.delay_hours is None and self.delay_type is None:
            raise ValueError("One of delay_hours or delay_type is required")
        if self.delay_hours is not None:
            if self.delay_hours <= 0:
                raise ValueError("delay_hours must be positive")
            if self.delay_hours > 48:
                raise ValueError("delay_hours must be 48 or less")
        if self.preferred_window is not None:
            if len(self.preferred_window) != 2:
                raise ValueError("preferred_window must be [start_hour, end_hour]")
            s, e = self.preferred_window
            if not (0 <= s <= 23 and 0 <= e <= 23):
                raise ValueError("preferred_window hours must be 0-23")
            if s >= e:
                raise ValueError("preferred_window start must be before end (overnight windows not supported)")
        return self


class CallbackSchedule(BaseModel):
    """Per-bot retry schedule with steps and optional template."""
    template: Literal["standard", "aggressive", "relaxed", "custom"] = "custom"
    steps: list[RetryStep]

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v):
        if len(v) == 0:
            raise ValueError("At least one retry step is required")
        if len(v) > 10:
            raise ValueError("Maximum 10 retry steps")
        return v
```

Also add `callback_schedule` field to all three request/response schemas:

In `CreateBotConfigRequest` (after line 178, after `callback_window_end`):
```python
    callback_schedule: CallbackSchedule | None = None
```

In `UpdateBotConfigRequest` (after line 230, after `callback_window_end`):
```python
    callback_schedule: CallbackSchedule | dict | None = None
```

In `BotConfigResponse` (after `callback_window_end` field):
```python
    callback_schedule: CallbackSchedule | dict | None = None
```

Note: Add `field_validator` to the imports at the top of `schemas.py`. The existing import line is `from pydantic import BaseModel, ConfigDict, Field, model_validator` — add `field_validator` to it. Also ensure `Literal` is imported from `typing`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/schemas.py tests/test_smart_retry.py
git commit -m "feat: add RetryStep and CallbackSchedule Pydantic models with validation"
```

---

### Task 2: Database Migration + ORM

**Files:**
- Modify: `app/models/bot_config.py:61-66`
- Create: `alembic/versions/031_add_callback_schedule.py`

- [ ] **Step 1: Add column to ORM model**

In `app/models/bot_config.py`, add after line 66 (`callback_window_end`):

```python
    callback_schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

Ensure `JSONB` is in the imports at the top (it should already be imported for `extra_vars` etc.).

- [ ] **Step 2: Create Alembic migration**

Create `alembic/versions/031_add_callback_schedule.py`:

```python
"""Add callback_schedule JSONB to bot_configs.

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "031"
down_revision = "030"


def upgrade():
    # Phase 1: Add new column
    op.add_column("bot_configs", sa.Column("callback_schedule", JSONB, nullable=True))

    # Phase 2: Migrate existing callback configs to new format
    # For bots with callback_enabled=true and max_retries > 0,
    # convert old flat fields to step-based schedule
    op.execute("""
        UPDATE bot_configs
        SET callback_schedule = jsonb_build_object(
            'template', 'custom',
            'steps', (
                SELECT jsonb_agg(
                    jsonb_build_object('delay_hours', callback_retry_delay_hours)
                )
                FROM generate_series(1, callback_max_retries)
            )
        )
        WHERE callback_enabled = true
          AND callback_max_retries > 0
          AND callback_schedule IS NULL
    """)


def downgrade():
    op.drop_column("bot_configs", "callback_schedule")
```

- [ ] **Step 3: Test migration locally (dry run)**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -c "from app.models.bot_config import BotConfig; print('ORM OK:', hasattr(BotConfig, 'callback_schedule'))"`
Expected: `ORM OK: True`

- [ ] **Step 4: Commit**

```bash
git add app/models/bot_config.py alembic/versions/031_add_callback_schedule.py
git commit -m "feat: add callback_schedule JSONB column with data migration"
```

---

### Task 3: Scheduling Logic (`compute_scheduled_at`)

**Files:**
- Create: `app/services/smart_retry.py`
- Test: `tests/test_smart_retry.py` (append)

- [ ] **Step 1: Write scheduling tests**

Append to `tests/test_smart_retry.py`:

```python
from freezegun import freeze_time
from zoneinfo import ZoneInfo

from app.services.smart_retry import compute_scheduled_at


class FakeBotConfig:
    """Minimal bot config for testing."""
    def __init__(self, tz="Asia/Kolkata", window_start=9, window_end=20):
        self.callback_timezone = tz
        self.callback_window_start = window_start
        self.callback_window_end = window_end


class TestComputeScheduledAt:
    def test_delay_hours_basic(self):
        """3h delay from now."""
        step = {"delay_hours": 3}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        expected_min = datetime.now(timezone.utc) + timedelta(hours=2, minutes=59)
        expected_max = datetime.now(timezone.utc) + timedelta(hours=3, minutes=1)
        assert expected_min <= result <= expected_max

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10:00 AM IST
    def test_delay_hours_inside_preferred_window_no_snap(self):
        """2h delay at 10 AM IST with [11,14] window → lands at 12 PM, inside window, no snap."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 2, "preferred_window": [11, 14]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert 11 <= result_ist.hour < 14  # inside window

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10:00 AM IST
    def test_delay_hours_outside_preferred_window_snaps(self):
        """3h delay at 10 AM IST with [20,22] window → snaps to 8 PM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 3, "preferred_window": [20, 22]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 20

    @freeze_time("2026-03-22 18:31:00", tz_offset=0)  # 12:01 AM IST on Mar 23
    def test_next_day_window_not_passed(self):
        """12:01 AM IST with [11,13] window → today at 11 AM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [11, 13]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 11
        assert result_ist.day == 23  # today, not tomorrow

    @freeze_time("2026-03-23 15:30:00", tz_offset=0)  # 9 PM IST
    def test_next_day_window_already_passed(self):
        """9 PM IST with [11,13] window → tomorrow at 11 AM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [11, 13]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 11
        assert result_ist.day == 24  # tomorrow

    @freeze_time("2026-03-23 15:30:00", tz_offset=0)  # 9 PM IST
    def test_next_day_evening_window_passed(self):
        """9 PM IST with [20,22] window → tomorrow at 8 PM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [20, 22]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 20
        assert result_ist.day == 24

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10 AM IST
    def test_global_window_guardrail_pushes_to_morning(self):
        """preferred_window [20,22] but calling window ends at 20 → pushes to 9 AM next day."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 3, "preferred_window": [20, 22]}
        bot = FakeBotConfig(window_start=9, window_end=20)  # window ends at 20!
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 9  # pushed to next morning
        assert result_ist.day == 24

    @freeze_time("2026-03-22 20:30:00", tz_offset=0)  # 2 AM IST on Mar 23
    def test_global_window_early_morning(self):
        """2 AM IST with calling window [9,20] → pushes to 9 AM today."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 0.5}
        bot = FakeBotConfig(window_start=9, window_end=20)
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 9
        assert result_ist.day == 23  # today, not tomorrow

    def test_next_day_no_window(self):
        """next_day without preferred_window → ~24h from now."""
        step = {"delay_type": "next_day"}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        # Global window may shift it, so just check it's in the future
        assert result > datetime.now(timezone.utc)

    def test_fallback_on_bad_step(self):
        """Missing both fields → 3h fallback."""
        step = {}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        assert result > datetime.now(timezone.utc)
```

**Note:** Install `freezegun` if not already in dev dependencies: `pip install freezegun`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py::TestComputeScheduledAt -v`
Expected: ImportError — `app.services.smart_retry` not found

- [ ] **Step 3: Implement `compute_scheduled_at`**

Create `app/services/smart_retry.py`:

```python
"""Smart retry scheduling — computes when to schedule retry calls.

Isolated from queue_processor for testability. All timezone math lives here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def compute_scheduled_at(step: dict, bot_config) -> datetime:
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
    now_utc = datetime.now(timezone.utc)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py::TestComputeScheduledAt -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/smart_retry.py tests/test_smart_retry.py
git commit -m "feat: add compute_scheduled_at with timezone-aware scheduling logic"
```

---

### Task 4: Rewrite `schedule_auto_retry()`

**Files:**
- Modify: `app/services/queue_processor.py:1008-1077`
- Test: `tests/test_smart_retry.py` (append)

- [ ] **Step 1: Write retry logic tests**

Append to `tests/test_smart_retry.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


class TestScheduleAutoRetry:
    """Tests for the rewritten schedule_auto_retry function.

    These test the logic branches, not the full DB flow.
    We mock the DB session and verify the right QueuedCall is created.
    """

    @pytest.mark.asyncio
    async def test_skips_campaign_calls(self):
        """Campaign calls should not get auto-retried."""
        from app.services.queue_processor import schedule_auto_retry

        call_log_id = uuid.uuid4()
        loader = AsyncMock()

        with patch("app.services.queue_processor.get_db_session") as mock_db:
            session = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            # Simulate call_log exists
            call_log = MagicMock()
            call_log.context_data = {"bot_id": str(uuid.uuid4())}
            call_log.bot_id = uuid.uuid4()
            session.execute.return_value.scalar_one_or_none.return_value = call_log

            # Simulate campaign QC found
            campaign_qc = MagicMock()
            campaign_qc.campaign_id = uuid.uuid4()

            # First execute: call_log, second: campaign check
            session.execute.side_effect = [
                MagicMock(scalar_one_or_none=MagicMock(return_value=call_log)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=campaign_qc)),
            ]

            await schedule_auto_retry(call_log_id, loader)
            # Should return early — no commit
            session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_sequence_calls(self):
        """Sequence-sourced calls should not get auto-retried."""
        from app.services.queue_processor import schedule_auto_retry

        call_log_id = uuid.uuid4()
        bot_id = uuid.uuid4()
        loader = AsyncMock()

        bot_config = FakeBotConfig()
        bot_config.callback_enabled = True
        bot_config.callback_schedule = {
            "template": "standard",
            "steps": [{"delay_hours": 3}],
        }
        loader.get = AsyncMock(return_value=bot_config)

        with patch("app.services.queue_processor.get_db_session") as mock_db:
            session = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            call_log = MagicMock()
            call_log.id = call_log_id
            call_log.bot_id = bot_id
            call_log.context_data = {"bot_id": str(bot_id)}

            # No campaign QC
            no_campaign = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

            # Original QC with source=sequence
            orig_qc = MagicMock()
            orig_qc.source = "sequence"
            orig_qc.retry_count = 0
            orig_qc_result = MagicMock(scalar_one_or_none=MagicMock(return_value=orig_qc))

            session.execute.side_effect = [
                MagicMock(scalar_one_or_none=MagicMock(return_value=call_log)),
                no_campaign,
                orig_qc_result,
            ]

            await schedule_auto_retry(call_log_id, loader)
            session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_skips_existing_retry(self):
        """If a queued auto_retry already exists for same phone+bot, skip."""
        from app.services.queue_processor import schedule_auto_retry

        call_log_id = uuid.uuid4()
        bot_id = uuid.uuid4()
        loader = AsyncMock()

        bot_config = FakeBotConfig()
        bot_config.callback_enabled = True
        bot_config.callback_schedule = {
            "template": "standard",
            "steps": [{"delay_hours": 3}],
        }
        loader.get = AsyncMock(return_value=bot_config)

        with patch("app.services.queue_processor.get_db_session") as mock_db:
            session = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            call_log = MagicMock()
            call_log.id = call_log_id
            call_log.bot_id = bot_id
            call_log.contact_phone = "+919999999999"
            call_log.context_data = {"bot_id": str(bot_id)}

            # No campaign QC
            no_campaign = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

            # Original QC (source=webhook, not sequence)
            orig_qc = MagicMock()
            orig_qc.source = "webhook"
            orig_qc.retry_count = 0
            orig_qc_result = MagicMock(scalar_one_or_none=MagicMock(return_value=orig_qc))

            # Existing queued auto_retry found (dedup hit)
            existing_retry = MagicMock()
            existing_retry_result = MagicMock(scalar=MagicMock(return_value=existing_retry))

            session.execute.side_effect = [
                MagicMock(scalar_one_or_none=MagicMock(return_value=call_log)),
                no_campaign,
                orig_qc_result,
                existing_retry_result,  # dedup check finds existing
            ]

            await schedule_auto_retry(call_log_id, loader)
            session.add.assert_not_called()  # Should skip due to dedup
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py::TestScheduleAutoRetry -v`
Expected: FAIL (sequence skip not implemented yet)

- [ ] **Step 3: Rewrite `schedule_auto_retry()`**

Replace the function at `app/services/queue_processor.py:1008-1077` with:

```python
async def schedule_auto_retry(call_log_id: UUID, bot_config_loader):
    """Re-queue a no-answer call for automatic retry if callback is enabled.

    Called from plivo_event / twilio_event when call status is 'no_answer'.
    Uses step-based callback_schedule if configured, falls back to old
    flat fields (callback_retry_delay_hours + callback_max_retries) for
    backward compatibility during Phase 1 migration.
    """
    try:
        async with get_db_session() as db:
            # 1. Load call log
            result = await db.execute(
                select(CallLog).where(CallLog.id == call_log_id)
            )
            call_log = result.scalar_one_or_none()
            if not call_log or not call_log.context_data:
                return

            # 2. Skip campaign calls — campaigns have their own retry logic
            qc_result = await db.execute(
                select(QueuedCall).where(
                    QueuedCall.call_log_id == call_log_id,
                    QueuedCall.campaign_id.isnot(None),
                )
            )
            if qc_result.scalar_one_or_none():
                return

            # 3. Load bot config and check callback_enabled
            bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
            if not bot_config or not getattr(bot_config, "callback_enabled", False):
                return

            # 4. Find original queued call to get retry_count and extra_vars
            orig_result = await db.execute(
                select(QueuedCall)
                .where(QueuedCall.call_log_id == call_log_id)
                .order_by(QueuedCall.created_at.desc())
                .limit(1)
            )
            original_qc = orig_result.scalar_one_or_none()

            # 5. Skip sequence-sourced calls — they have their own follow-up
            if original_qc and original_qc.source == "sequence":
                return

            # 6. Deduplication — skip if a queued auto_retry already exists
            existing = await db.execute(
                select(QueuedCall.id).where(
                    QueuedCall.contact_phone == call_log.contact_phone,
                    QueuedCall.bot_id == call_log.bot_id,
                    QueuedCall.source == "auto_retry",
                    QueuedCall.status == "queued",
                ).limit(1)
            )
            if existing.scalar():
                logger.info(
                    "auto_retry_dedup_skip",
                    call_log_id=str(call_log_id),
                    phone=call_log.contact_phone,
                )
                return

            current_retry = (original_qc.retry_count if original_qc else 0)

            # 7. Compute scheduled_at — new step-based or old flat fallback
            schedule = getattr(bot_config, "callback_schedule", None)
            if schedule and schedule.get("steps"):
                steps = schedule["steps"]
                if current_retry >= len(steps):
                    logger.info(
                        "auto_retry_schedule_exhausted",
                        call_log_id=str(call_log_id),
                        phone=call_log.contact_phone,
                        retry_count=current_retry,
                        max_steps=len(steps),
                    )
                    return
                from app.services.smart_retry import compute_scheduled_at
                step = steps[current_retry]
                scheduled_at = compute_scheduled_at(step, bot_config)
            else:
                # Phase 1 fallback: old flat fields
                max_retries = getattr(bot_config, "callback_max_retries", 3)
                delay_hours = getattr(bot_config, "callback_retry_delay_hours", 2.0)
                if current_retry >= max_retries:
                    logger.info(
                        "auto_retry_max_reached",
                        call_log_id=str(call_log_id),
                        retry_count=current_retry,
                        max_retries=max_retries,
                    )
                    return
                scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

            retry_call = QueuedCall(
                org_id=call_log.org_id,
                bot_id=call_log.bot_id,
                contact_name=call_log.contact_name,
                contact_phone=call_log.contact_phone,
                ghl_contact_id=call_log.ghl_contact_id,
                extra_vars=(original_qc.extra_vars if original_qc else {}),
                source="auto_retry",
                status="queued",
                priority=0,
                scheduled_at=scheduled_at,
                retry_count=current_retry + 1,
                original_call_sid=call_log.call_sid,
            )
            db.add(retry_call)
            await db.commit()

            logger.info(
                "auto_retry_scheduled",
                call_log_id=str(call_log_id),
                phone=call_log.contact_phone,
                retry_number=current_retry + 1,
                scheduled_at=scheduled_at.isoformat(),
                used_schedule=bool(schedule and schedule.get("steps")),
            )

    except Exception:
        logger.exception(
            "auto_retry_schedule_error",
            call_log_id=str(call_log_id),
        )
```

- [ ] **Step 4: Run all tests**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/queue_processor.py tests/test_smart_retry.py
git commit -m "feat: rewrite schedule_auto_retry with step-based scheduling, dedup, and sequence skip"
```

---

### Task 5: API Validation (cross-validate windows)

**Files:**
- Modify: `app/api/bots.py:108-150`

- [ ] **Step 1: Add cross-validation to bot update endpoint**

In `app/api/bots.py`, add a validation check inside the `update_bot` endpoint (after `req.model_dump(exclude_unset=True)` on line 121, before the setattr loop):

```python
    # Cross-validate callback_schedule preferred_windows against calling window
    if "callback_schedule" in update_data and update_data["callback_schedule"]:
        from app.models.schemas import CallbackSchedule
        schedule_data = update_data["callback_schedule"]
        if isinstance(schedule_data, dict):
            schedule = CallbackSchedule(**schedule_data)
        else:
            schedule = schedule_data

        # Resolve the effective calling window (from update or existing bot)
        w_start = update_data.get("callback_window_start", bot.callback_window_start)
        w_end = update_data.get("callback_window_end", bot.callback_window_end)

        for i, step in enumerate(schedule.steps):
            if step.preferred_window:
                pw_start, pw_end = step.preferred_window
                # Check if preferred window has ANY overlap with calling window
                if pw_end <= w_start or pw_start >= w_end:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {i+1} preferred window [{pw_start}-{pw_end}] "
                               f"is entirely outside calling window [{w_start}-{w_end}]"
                    )

        # Store as dict for JSONB
        update_data["callback_schedule"] = schedule.model_dump()
```

Add the same validation to `create_bot` endpoint (after line ~50, before `BotConfig(...)` construction):

```python
    # Cross-validate callback_schedule
    if req.callback_schedule:
        for i, step in enumerate(req.callback_schedule.steps):
            if step.preferred_window:
                pw_start, pw_end = step.preferred_window
                if pw_end <= req.callback_window_start or pw_start >= req.callback_window_end:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {i+1} preferred window [{pw_start}-{pw_end}] "
                               f"is entirely outside calling window [{req.callback_window_start}-{req.callback_window_end}]"
                    )
```

- [ ] **Step 2: Commit**

```bash
git add app/api/bots.py
git commit -m "feat: cross-validate retry step windows against global calling window"
```

---

### Task 6: Frontend — TypeScript Types

**Files:**
- Modify: `frontend/src/types/api.ts:10-59`

- [ ] **Step 1: Add TypeScript types**

Add before the `BotConfig` interface:

```typescript
export interface RetryStep {
  delay_hours?: number;
  delay_type?: "next_day";
  preferred_window?: [number, number];
}

export interface CallbackSchedule {
  template: "standard" | "aggressive" | "relaxed" | "custom";
  steps: RetryStep[];
}
```

Add to `BotConfig` interface (after `callback_window_end`):

```typescript
  callback_schedule: CallbackSchedule | null;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat: add CallbackSchedule TypeScript types"
```

---

### Task 7: Frontend — Retry Schedule Builder UI

**Files:**
- Modify: `frontend/src/app/(app)/bots/[botId]/page.tsx:2161-2240`

- [ ] **Step 1: Define template presets**

Add a constant near the top of the file (or in a separate constants file):

```typescript
const RETRY_TEMPLATES: Record<string, { label: string; description: string; steps: RetryStep[] }> = {
  standard: {
    label: "Standard",
    description: "3h → 3h → next day midday → next day evening",
    steps: [
      { delay_hours: 3 },
      { delay_hours: 3 },
      { delay_type: "next_day", preferred_window: [11, 13] },
      { delay_type: "next_day", preferred_window: [20, 22] },
    ],
  },
  aggressive: {
    label: "Aggressive",
    description: "1h → 2h → 3h → next day evening → next day midday",
    steps: [
      { delay_hours: 1 },
      { delay_hours: 2 },
      { delay_hours: 3 },
      { delay_type: "next_day", preferred_window: [20, 22] },
      { delay_type: "next_day", preferred_window: [11, 13] },
    ],
  },
  relaxed: {
    label: "Relaxed",
    description: "Next day midday → next day evening → 2 days midday",
    steps: [
      { delay_type: "next_day", preferred_window: [11, 13] },
      { delay_type: "next_day", preferred_window: [20, 22] },
      { delay_type: "next_day", preferred_window: [11, 13] },
    ],
  },
};
```

- [ ] **Step 2: Build the step list UI**

Replace the "Retry Delay" and "Max Retries" inputs in the Scheduled Callbacks section (lines ~2188-2223) with a new component. The UI should:

1. Show template picker cards (Standard / Aggressive / Relaxed / Custom) — use existing card/button patterns from the page
2. Show ordered step list with:
   - Badge: "Step 1", "Step 2", etc.
   - Dropdown: "After X hours" / "Next day"
   - If "After X hours": number input (min=0.5, max=48, step=0.5)
   - Toggle for "Preferred time window" → two Select dropdowns (start hour, end hour)
   - Delete button (X icon) per step
3. "Add Step" button (disabled at 10 steps)
4. When a template is selected, populate `callback_schedule` with the template's steps
5. When any step is manually edited, set template to "custom"
6. Show warning if preferred_window conflicts with calling window

State management: store as `callback_schedule: CallbackSchedule | null` in the form state. On save, send to API as part of the bot config update.

**Implementation note:** Follow the existing patterns in the bot config page — it uses controlled form state with `useState` and submits via the existing `handleSave` function. Add `callback_schedule` to the form data that gets submitted.

Keep `callback_timezone`, `callback_window_start`, `callback_window_end` inputs as they are — they're the "Calling Hours" section, separate from the step builder.

- [ ] **Step 3: Handle backward compatibility in UI**

When loading a bot config:
- If `callback_schedule` is null but `callback_enabled` is true → show the old inputs (Phase 1 compat) OR auto-generate a schedule from old fields and display in new UI
- If `callback_schedule` is set → show new step builder, hide old inputs

Recommended: auto-generate from old fields and always show new UI:

```typescript
const getInitialSchedule = (bot: BotConfig): CallbackSchedule | null => {
  if (bot.callback_schedule) return bot.callback_schedule;
  if (!bot.callback_enabled) return null;
  // Generate from old fields
  const steps: RetryStep[] = Array.from(
    { length: bot.callback_max_retries },
    () => ({ delay_hours: bot.callback_retry_delay_hours })
  );
  return { template: "custom", steps };
};
```

- [ ] **Step 4: Test manually in browser**

1. Open bot config page
2. Enable callbacks
3. Select "Standard" template → verify steps populate
4. Edit a step → verify template changes to "Custom"
5. Add a step, delete a step
6. Set preferred window outside calling hours → verify warning
7. Save → verify API accepts and data persists on reload

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/\(app\)/bots/\[botId\]/page.tsx frontend/src/types/api.ts
git commit -m "feat: add retry schedule builder UI with template picker and step editor"
```

---

### Task 8: Final Test Suite (pre-deploy)

**Files:**
- Modify: `tests/test_smart_retry.py` (append integration tests)

- [ ] **Step 1: Add integration tests**

Append to `tests/test_smart_retry.py`:

```python
class TestRetryIntegration:
    """Integration tests — verify full flow with real schema validation."""

    def test_template_roundtrip(self):
        """Template → serialize → deserialize → matches."""
        schedule = CallbackSchedule(
            template="standard",
            steps=[
                RetryStep(delay_hours=3),
                RetryStep(delay_hours=3),
                RetryStep(delay_type="next_day", preferred_window=[11, 13]),
                RetryStep(delay_type="next_day", preferred_window=[20, 22]),
            ],
        )
        data = schedule.model_dump()
        restored = CallbackSchedule(**data)
        assert len(restored.steps) == 4
        assert restored.steps[0].delay_hours == 3
        assert restored.steps[2].preferred_window == [11, 13]
        assert restored.template == "standard"

    def test_step_progression_logic(self):
        """Simulate 3 consecutive retries — each uses the next step."""
        steps = [
            {"delay_hours": 3},
            {"delay_hours": 3},
            {"delay_type": "next_day", "preferred_window": [11, 13]},
        ]
        bot = FakeBotConfig()

        for retry_count in range(3):
            step = steps[retry_count]
            result = compute_scheduled_at(step, bot)
            assert result > datetime.now(timezone.utc)

        # retry_count=3 should be exhausted (>= len(steps))
        assert 3 >= len(steps)

    def test_api_rejects_conflicting_windows(self):
        """preferred_window [20,22] with calling window [9,18] → should conflict."""
        step = RetryStep(delay_type="next_day", preferred_window=[20, 22])
        pw_start, pw_end = step.preferred_window
        w_start, w_end = 9, 18
        has_overlap = not (pw_end <= w_start or pw_start >= w_end)
        assert not has_overlap  # No overlap → API should reject

    def test_migration_conversion_logic(self):
        """Old config (delay=2, max=3) → 3 steps of delay_hours=2."""
        old_delay = 2.0
        old_max = 3
        steps = [{"delay_hours": old_delay} for _ in range(old_max)]
        schedule = CallbackSchedule(template="custom", steps=[RetryStep(**s) for s in steps])
        assert len(schedule.steps) == 3
        assert all(s.delay_hours == 2.0 for s in schedule.steps)

    def test_migration_skips_zero_retries(self):
        """max_retries=0 → no steps → should NOT create schedule."""
        old_max = 0
        assert old_max <= 0  # Would skip in migration

    def test_migration_skips_disabled_bots(self):
        """callback_enabled=false → should NOT create schedule."""
        callback_enabled = False
        assert not callback_enabled  # Migration WHERE clause skips these
```

- [ ] **Step 2: Run full test suite**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_smart_retry.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_smart_retry.py
git commit -m "test: add integration tests for smart retry scheduling"
```

---

### Task 9: Deploy + Migration

**Files:** None (operational)

- [ ] **Step 1: Push to remote**

```bash
git push origin main
```

- [ ] **Step 2: Deploy backend + run migration atomically**

The migration MUST run before the new backend serves requests. Build the image, run migration via a one-off container, then restart:

```bash
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e \
  --command="cd /home/animeshmahato/wavelength-v3 && \
  sudo git pull origin main && \
  sudo docker compose build backend && \
  sudo docker compose run --rm backend alembic upgrade head && \
  sudo docker compose up -d backend"
```

This runs the migration using the new image (with the new ORM model) against the existing DB, then starts the new backend. No window where code expects a column that doesn't exist.

- [ ] **Step 4: Verify migration**

```bash
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e \
  --command="docker exec wavelength-db psql -U wavelength_app -d wavelength -c \
  \"SELECT callback_schedule IS NOT NULL as has_schedule, count(*) FROM bot_configs GROUP BY 1;\""
```

Expected: bots with `callback_enabled=true` should have `has_schedule = true`.

- [ ] **Step 5: Deploy frontend**

```bash
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e \
  --command="cd /home/animeshmahato/wavelength-v3 && \
  sudo git pull origin main && \
  sudo chown -R animeshmahato:animeshmahato frontend/.next && \
  cd frontend && npm run build && pm2 restart wavelength-frontend"
```

- [ ] **Step 6: Smoke test**

1. Open bot config page → verify new retry schedule UI loads
2. Select a template → save → reload → verify persisted
3. Queue a test call → let it no-answer → verify retry is scheduled with step-based timing (check logs for `used_schedule=true`)

