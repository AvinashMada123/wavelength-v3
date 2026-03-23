# Smart Retry Schedules — Design Spec

**Date:** 2026-03-23
**Status:** Draft (v2 — post-audit fixes)

## Problem

The current retry system uses a flat delay (`callback_retry_delay_hours`) applied uniformly to every retry attempt. Our data (14K calls, 60 days) shows:

- **Evening calls (8-10 PM IST) connect 40-60% more often** than morning calls (33% vs 56%)
- **3 attempts is the sweet spot** — conversion jumps from 48% to 65%
- No ability to vary timing per attempt or target high-pickup windows

## Solution

Replace the flat retry config with a **per-bot step-based retry schedule**. Each step defines when and how to retry. Pre-built templates provide smart defaults based on our call data.

## Data Model

### New Field: `callback_schedule` on `bot_configs`

```python
callback_schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

### Schema (Pydantic validation)

```python
class RetryStep(BaseModel):
    delay_hours: float | None = None
    delay_type: Literal["next_day"] | None = None  # mutually exclusive with delay_hours
    preferred_window: list[int] | None = None  # [start_hour, end_hour] in bot timezone, 0-23

    @model_validator(mode="after")
    def validate_step(self):
        # Exactly one of delay_hours or delay_type must be set
        if self.delay_hours is not None and self.delay_type is not None:
            raise ValueError("delay_hours and delay_type are mutually exclusive")
        if self.delay_hours is None and self.delay_type is None:
            raise ValueError("One of delay_hours or delay_type is required")
        # delay_hours bounds
        if self.delay_hours is not None:
            if self.delay_hours <= 0:
                raise ValueError("delay_hours must be positive")
            if self.delay_hours > 48:
                raise ValueError("delay_hours must be 48 or less")
        # preferred_window validation
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

**Design decisions from audit:**
- `preferred_window` is `list[int]` not `tuple[int, int]` — matches JSON/JSONB semantics (no tuple type in JSON). Length validated to exactly 2.
- `template` is a `Literal` not `str` — prevents typos.
- `delay_hours` capped at 48 — matches frontend constraint.
- **Overnight windows (e.g., [22, 6]) are explicitly unsupported** — the range check logic and the global calling-window guardrail both assume non-wrapping ranges. This matches the existing `callback_window_start/end` behavior. If needed later, overnight support can be added as a separate feature.

### Templates

| Template | Steps | Use Case |
|---|---|---|
| **Standard** | `3h → 3h → next_day [11,13] → next_day [20,22]` | Default, data-driven |
| **Aggressive** | `1h → 2h → 3h → next_day [20,22] → next_day [11,13]` | Time-sensitive (masterclass tomorrow) |
| **Relaxed** | `next_day [11,13] → next_day [20,22] → next_day [11,13]` | Lower-priority follow-ups |

### Fields Removed (via phased migration — see Migration section)

- `callback_retry_delay_hours` — replaced by `steps[].delay_hours`
- `callback_max_retries` — replaced by `len(steps)`

### Fields Kept

- `callback_enabled` — master toggle, unchanged
- `callback_timezone` — used to interpret preferred_window hours
- `callback_window_start` / `callback_window_end` — global guardrails, always respected
- `callback_greeting_template` — unchanged

## Scheduling Logic

### `schedule_auto_retry()` changes

The function order is: load call_log → load bot_config → check callback_enabled → find original QueuedCall → skip campaigns → skip sequences → dedup check → compute schedule → create retry.

```python
async def schedule_auto_retry(call_log_id, bot_config_loader):
    # 1. Load call_log from DB
    call_log = ...

    # 2. Skip campaign calls (existing behavior)
    if call_log.campaign_id:
        return

    # 3. Load bot_config, check callback_enabled
    bot_config = await bot_config_loader.get(str(call_log.bot_id))
    if not bot_config or not bot_config.callback_enabled:
        return

    # 4. Find original QueuedCall to read retry_count
    original_queued_call = await db.execute(
        select(QueuedCall).where(QueuedCall.call_log_id == call_log.id)
    )
    original_qc = original_queued_call.scalar()

    # 5. Skip sequence-sourced calls (NEW)
    if original_qc and original_qc.source == "sequence":
        return

    # 6. Deduplication: skip if a queued auto_retry already exists for this phone+bot (NEW)
    existing = await db.execute(
        select(QueuedCall.id).where(
            QueuedCall.contact_phone == call_log.contact_phone,
            QueuedCall.bot_id == call_log.bot_id,
            QueuedCall.source == "auto_retry",
            QueuedCall.status == "queued",
        ).limit(1)
    )
    if existing.scalar():
        logger.info("auto_retry_dedup_skip", phone=call_log.contact_phone)
        return

    # 7. Read schedule (NEW) — fall back to old fields during Phase 1
    schedule = bot_config.callback_schedule
    if schedule and schedule.get("steps"):
        steps = schedule["steps"]
        current_retry = original_qc.retry_count if original_qc else 0
        if current_retry >= len(steps):
            logger.info("auto_retry_schedule_exhausted", retry=current_retry, max=len(steps))
            return
        step = steps[current_retry]
        scheduled_at = compute_scheduled_at(step, bot_config)
    else:
        # Phase 1 fallback: use old flat fields
        delay_hours = getattr(bot_config, "callback_retry_delay_hours", 2.0)
        max_retries = getattr(bot_config, "callback_max_retries", 3)
        current_retry = original_qc.retry_count if original_qc else 0
        if current_retry >= max_retries:
            return
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

    # 8. Create new QueuedCall with incremented retry_count
    retry_call = QueuedCall(
        org_id=call_log.org_id,
        bot_id=call_log.bot_id,
        contact_name=call_log.contact_name,
        contact_phone=call_log.contact_phone,
        ghl_contact_id=call_log.ghl_contact_id,
        extra_vars=original_qc.extra_vars if original_qc else {},
        source="auto_retry",
        status="queued",
        priority=0,
        scheduled_at=scheduled_at,
        retry_count=(current_retry + 1),
        original_call_sid=call_log.call_sid,
    )
    db.add(retry_call)
    await db.commit()
```

### `compute_scheduled_at()` — new function

```python
def compute_scheduled_at(step: dict, bot_config) -> datetime:
    """Compute the UTC datetime for a retry based on step config.

    For delay_hours: base = now + delay. If preferred_window is set and
    base lands outside it, snap forward to next window opening. delay_hours
    acts as a MINIMUM delay when combined with preferred_window.

    For next_day: find the next calendar day (in bot timezone) where the
    preferred_window start hasn't passed yet. If no preferred_window,
    schedule for tomorrow at the same time.

    Final guardrail: if the result falls outside the bot's global
    callback_window, push forward to the next window opening.

    DST note: we use datetime.replace(hour=X) which may produce ambiguous
    times on DST transition days. ZoneInfo resolves these deterministically
    (post-transition wall time). This is acceptable — worst case a retry
    fires 1 hour early/late on 2 days per year.
    """
    tz = ZoneInfo(bot_config.callback_timezone or "Asia/Kolkata")
    now_local = datetime.now(tz)
    window = step.get("preferred_window")

    # --- Step 1: Compute base time ---
    if step.get("delay_hours"):
        base = datetime.now(timezone.utc) + timedelta(hours=step["delay_hours"])
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
            base = datetime.now(timezone.utc) + timedelta(days=1)
    else:
        base = datetime.now(timezone.utc) + timedelta(hours=3)  # fallback

    # --- Step 2: Snap to preferred_window (delay_hours path only) ---
    # For next_day, base is already set to window start, so this is a no-op.
    # For delay_hours, this enforces the window as a constraint (delay becomes minimum).
    if window and step.get("delay_hours"):
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
    window_start = bot_config.callback_window_start  # e.g., 9
    window_end = bot_config.callback_window_end      # e.g., 20
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

### Key semantics

- **`delay_hours: 3`** — schedule retry at least 3 hours from now. If that falls outside `preferred_window`, snap forward to next window opening. `delay_hours` is a **minimum delay**, not exact, when combined with `preferred_window`.
- **`delay_type: "next_day"`** — next occurrence (in bot timezone) where the preferred_window start hasn't passed. If it's 12:01 AM and window is [11, 13], that's today at 11 AM (~11 hours). If it's 9 PM and window is [20, 22], that's tomorrow at 8 PM (~23 hours). Note: `next_day` is a misnomer when the window is today — it means "next available slot," not literally tomorrow.
- **Global calling window always wins** — if `scheduled_at` ends up outside `callback_window_start/end`, it gets pushed to the next window opening.
- **Preferred window conflict** — if a step's `preferred_window` falls entirely outside the global calling window (e.g., preferred [20, 22] but `callback_window_end=20`), the global window wins and pushes to next morning. The API will **reject** this configuration with a validation error at save time, not just warn in the UI.
- **DST transitions** — `datetime.replace(hour=X)` may produce ambiguous local times on DST transition days. ZoneInfo resolves deterministically. Worst case: a retry fires ~1 hour early or late on 2 days/year. Acceptable for this use case.

## Trigger Conditions

`no_answer` and `busy` both already trigger `schedule_auto_retry()` — `busy` is mapped to `no_answer` in `_map_plivo_status()`. No change needed here.

**Excluded from auto-retry:**
- Campaign calls (`campaign_id is not None`) — have separate retry logic (existing)
- Sequence calls (`source == "sequence"`) — have their own follow-up engine (NEW)

**Deduplication (NEW):**
Before creating a retry QueuedCall, check if one already exists for the same `contact_phone + bot_id` with `source=auto_retry, status=queued`. If so, skip. Prevents duplicate retries from race conditions (e.g., two near-simultaneous no_answer events).

## Migration Strategy (Phased)

### Phase 1: Add new, keep old (non-breaking)

**Alembic migration:**
```sql
ALTER TABLE bot_configs ADD COLUMN callback_schedule JSONB;
```

**Code changes:**
- Add `callback_schedule` to ORM model, request/response schemas
- `schedule_auto_retry()` checks `callback_schedule` first, falls back to old `callback_retry_delay_hours` + `callback_max_retries` if null
- Frontend shows new step builder UI; if `callback_schedule` is null, displays the old simple inputs (backward compat)
- API accepts both: setting `callback_schedule` takes precedence; old fields still writable

### Phase 2: Data migration (same Alembic migration, `op.execute` block)

```python
# For each bot with callback_enabled=True AND callback_max_retries > 0:
# Convert old fields to new format
UPDATE bot_configs
SET callback_schedule = jsonb_build_object(
    'template', 'custom',
    'steps', (
        SELECT jsonb_agg(jsonb_build_object('delay_hours', callback_retry_delay_hours))
        FROM generate_series(1, callback_max_retries)
    )
)
WHERE callback_enabled = true
  AND callback_max_retries > 0
  AND callback_schedule IS NULL;
```

**Edge case:** Bots with `callback_max_retries=0` or `callback_enabled=false` get `callback_schedule=NULL` — no migration needed, no steps to generate.

### Phase 3: Drop old columns (separate PR, after Phase 1+2 are stable in production)

```sql
ALTER TABLE bot_configs DROP COLUMN callback_retry_delay_hours;
ALTER TABLE bot_configs DROP COLUMN callback_max_retries;
```

- Remove all references to old fields in: ORM model, Pydantic schemas (CreateBotConfigRequest, UpdateBotConfigRequest, BotConfigResponse), API handlers, frontend TypeScript types, frontend form
- Only ship after Phase 1+2 have been in production for at least a few days

## API Changes

### Bot config schemas (Phase 1)

Add to `CreateBotConfigRequest`, `UpdateBotConfigRequest`, and `BotConfigResponse`:

```python
callback_schedule: CallbackSchedule | None = None
```

### Validation at API level

When saving a bot config with `callback_schedule`:
1. Validate via `CallbackSchedule` Pydantic model (structure, bounds, mutual exclusivity)
2. **Cross-validate preferred windows against global calling window:** for each step with `preferred_window`, check that the window overlaps with `[callback_window_start, callback_window_end]`. If not, return 422 with a clear error message.

### Templates endpoint (optional, frontend can hardcode)

```
GET /api/bots/retry-templates
→ { "standard": {...}, "aggressive": {...}, "relaxed": {...} }
```

Frontend can hardcode these to avoid an API call. If templates evolve, move to API later.

## Frontend Changes

### Bot Config Page — Callbacks Section

Replace "Retry Delay" + "Max Retries" inputs with:

1. **Template Picker** — 4 cards: Standard / Aggressive / Relaxed / Custom. Selecting a template pre-fills the step list. Editing any step auto-switches template to "Custom".

2. **Step List** — Ordered list, each step shows:
   - Step number badge (1, 2, 3...)
   - Delay type: dropdown "After X hours" or "Next day"
   - If "After X hours": number input (0.5-48, step 0.5)
   - Preferred window: optional toggle → two hour dropdowns (start/end) when enabled
   - Delete button (trash icon)
   - Steps are drag-reorderable

3. **Add Step** button at bottom (disabled if 10 steps reached)

4. **Validation:**
   - If any step's preferred_window falls outside calling window → red error, block save
   - If no steps with callback_enabled=true → error
   - Visual preview: "Retry 1 in 3h, Retry 2 in 3h, Retry 3 next day 11AM-1PM, Retry 4 next day 8-10PM"

### TypeScript types

```typescript
interface RetryStep {
  delay_hours?: number;
  delay_type?: "next_day";
  preferred_window?: [number, number];
}

interface CallbackSchedule {
  template: "standard" | "aggressive" | "relaxed" | "custom";
  steps: RetryStep[];
}

// Add to BotConfig interface:
callback_schedule: CallbackSchedule | null;
```

Phase 3: remove `callback_retry_delay_hours` and `callback_max_retries` from BotConfig interface.

## Interactions with Other Systems

| System | Impact | Notes |
|---|---|---|
| **Campaigns** | No change | Campaign calls excluded from auto-retry (existing) |
| **Sequences** | Minor change | Sequence calls now explicitly excluded from auto-retry |
| **Circuit breaker** | No change | Blocks at bot level, independent of retry logic |
| **Stale processing cleanup** | No change | Resets stuck `processing` entries regardless of retry config |
| **Concurrent call limits** | No change | Retry creates a new QueuedCall, processed like any other |
| **Billing** | No change | Each retry attempt billed independently when it connects |
| **Calling window** | Enhanced | Global guardrail still applies; API now validates preferred_window against it |
| **`_process_single_call`** | No change needed | Existing window check at execution time is a safety net; `compute_scheduled_at` handles scheduling correctly |

## Testing Strategy

### Unit Tests (`tests/test_smart_retry.py`)

| Test | What It Verifies |
|---|---|
| `test_compute_scheduled_at_delay_hours` | Basic: now + 3h returns correct UTC |
| `test_compute_scheduled_at_next_day_with_window` | next_day + [11,13] window → correct timezone-aware time |
| `test_compute_scheduled_at_next_day_no_window` | next_day without window → tomorrow same time |
| `test_next_day_window_not_passed_yet` | 12:01 AM with [11,13] → today at 11 AM |
| `test_next_day_window_already_passed` | 9 PM with [11,13] → tomorrow at 11 AM |
| `test_next_day_evening_window_already_passed` | 9 PM with [20,22] → tomorrow at 8 PM |
| `test_delay_hours_inside_preferred_window` | 10 AM + 2h delay + [11,14] window → 12 PM (no snap) |
| `test_delay_hours_outside_preferred_window_snaps` | 10 AM + 3h delay + [20,22] window → snaps to 8 PM |
| `test_delay_hours_minimum_with_window` | Verifies delay_hours acts as minimum delay |
| `test_global_window_guardrail_pushes_to_morning` | preferred [20,22] + calling window ends 20 → pushes to 9 AM next day |
| `test_global_window_guardrail_same_day` | 2 AM scheduled + calling window [9,20] → pushes to 9 AM today |
| `test_schedule_exhausted` | retry_count >= len(steps) → no retry created |
| `test_dedup_skip` | Existing queued auto_retry for same phone+bot → skip |
| `test_sequence_skip` | source="sequence" → no auto-retry |
| `test_campaign_skip` | campaign_id set → no auto-retry (existing behavior) |
| `test_fallback_to_old_fields` | callback_schedule=None → uses callback_retry_delay_hours (Phase 1 compat) |
| `test_pydantic_valid_step` | Valid step configs accepted |
| `test_pydantic_rejects_both_delay_fields` | Both delay_hours + delay_type → error |
| `test_pydantic_rejects_neither_delay_field` | Neither set → error |
| `test_pydantic_rejects_negative_delay` | delay_hours=-1 → error |
| `test_pydantic_rejects_excessive_delay` | delay_hours=100 → error |
| `test_pydantic_rejects_bad_window` | [25, 3] → error |
| `test_pydantic_rejects_overnight_window` | [22, 6] → error with clear message |
| `test_pydantic_rejects_empty_steps` | steps=[] → error |
| `test_pydantic_rejects_too_many_steps` | 11 steps → error |
| `test_template_literal_validation` | template="invalid" → error |

### Integration Tests

| Test | What It Verifies |
|---|---|
| `test_full_retry_flow_with_schedule` | Queue call → no_answer → retry queued at step[0] time → verify QueuedCall |
| `test_retry_step_progression` | 3 no_answers → verify each retry uses correct step from schedule |
| `test_template_api_roundtrip` | POST bot with template → GET returns expanded steps |
| `test_backward_compat_no_schedule` | Bot with old fields only → retries still work (Phase 1) |
| `test_api_rejects_conflicting_windows` | preferred_window outside calling_window → 422 |
| `test_migration_conversion` | Old config (delay=2, max=3) → correct new format |
| `test_migration_skips_disabled_bots` | callback_enabled=false → callback_schedule stays null |
| `test_migration_skips_zero_retries` | callback_max_retries=0 → callback_schedule stays null |

## Files Modified

| File | Change |
|---|---|
| `app/models/bot_config.py` | Add `callback_schedule` JSONB column |
| `app/models/schemas.py` | Add `CallbackSchedule`, `RetryStep` models; add `callback_schedule` to request/response schemas |
| `app/services/queue_processor.py` | Rewrite `schedule_auto_retry()`, add `compute_scheduled_at()`, add sequence skip + dedup |
| `app/api/bots.py` | Accept/validate `callback_schedule`, cross-validate against calling window |
| `alembic/versions/xxx_add_callback_schedule.py` | Add column + data migration |
| `frontend/src/types/api.ts` | Add `CallbackSchedule`, `RetryStep` types to BotConfig |
| `frontend/src/app/(app)/bots/[botId]/page.tsx` | Replace retry inputs with template picker + step builder |
| `tests/test_smart_retry.py` | All unit + integration tests |
