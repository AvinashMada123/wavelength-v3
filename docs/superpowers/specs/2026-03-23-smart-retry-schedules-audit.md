# Smart Retry Schedules — Design Audit

**Date**: 2026-03-23
**Auditor**: Claude (architecture review)
**Verdict**: Solid core design, 14 issues to address before implementation

---

## 1. CRITICAL: "busy" Status Already Maps to "no_answer"

**Finding**: The design says "Both no_answer AND busy trigger retries (previously only no_answer)." But in `app/plivo/routes.py:303`, Plivo `busy` already maps to `"no_answer"` in the status mapping. So busy calls **already trigger** `schedule_auto_retry`. The design is solving a non-problem here, or worse, might add a second retry path for busy calls.

**Fix**: Verify this is already handled. If the intent is to treat busy differently (e.g., shorter retry delay for busy vs. no_answer), pass the raw Plivo status into `schedule_auto_retry` so the step selection can vary. Otherwise, remove this from the spec as a no-op.

---

## 2. CRITICAL: Dual Retry Paths — `schedule_auto_retry` vs. `create_scheduled_callback`

**Finding**: The codebase has TWO independent retry/callback mechanisms:
1. `schedule_auto_retry()` in queue_processor.py — triggered by Plivo/Twilio events on `no_answer`
2. `create_scheduled_callback()` in callback_scheduler.py — triggered by the LLM during a call (the bot's tool call when a person says "call me back later")

The design doesn't clarify which path gets the new step-based logic, or both. These paths use different `source` values (`"auto_retry"` vs `"callback"`). If only `schedule_auto_retry` gets the new logic, LLM-scheduled callbacks still use the old `callback_retry_delay_hours` default. If both get it, the callback_scheduler's natural-language time parsing conflicts with step-based scheduling.

**Fix**: Spec must explicitly state:
- `schedule_auto_retry` → uses `callback_schedule.steps[retry_count]` for delay/window
- `create_scheduled_callback` → keeps existing behavior (user-requested time, not step-based)
- Both paths respect `callback_window_start/end` as guardrails (already true)

---

## 3. HIGH: DST Transition Bug in `next_day` + `preferred_window`

**Finding**: "tomorrow at preferred_window[0] in bot timezone" is ambiguous during DST transitions. Example: Brazil (America/Sao_Paulo) springs forward at midnight — `00:00` becomes `01:00`. If you compute "tomorrow at 11:00" using `datetime.replace(hour=11)`, you get the correct wall-clock time because `ZoneInfo` handles this. BUT during fall-back, 2 AM happens twice. If `preferred_window = [1, 3]`, you could schedule into the ambiguous fold.

**Fix**: Always use `ZoneInfo` (not `pytz`) with `datetime.replace()` — Python's `zoneinfo` module handles folds correctly by default (picks the post-transition time). Document this behavior. The existing `enforce_calling_window` in callback_scheduler.py already uses `ZoneInfo`, so this is likely fine, but the spec should explicitly state it.

---

## 4. HIGH: `next_day` When Called at 11:59 PM — "Tomorrow" Is Only 1 Minute Away

**Finding**: If a call fails at 11:59 PM local time and the step says `delay_type: "next_day", preferred_window: [11, 13]`, the retry is scheduled for 11:00 AM the next calendar day — only ~11 hours away. That's fine. But what if it fails at 12:01 AM? "Next day" would be tomorrow's 11:00 AM — nearly 35 hours away. Is "next_day" always the next calendar day, or "at least 12 hours from now"?

**Fix**: Define "next_day" precisely in the spec. Recommendation: "next_day" means the next calendar day in the bot's timezone. If the current time is before `preferred_window[0]`, use today instead (the window hasn't passed yet). Add a minimum gap (e.g., 4 hours) to prevent a 12:01 AM failure from scheduling at 11:00 AM the same day (only 11 hours away might be fine, but a failure at 10:55 AM scheduling for 11:00 AM the same day is too aggressive).

---

## 5. HIGH: Migration Risk — Old Columns Still Referenced Everywhere

**Finding**: `callback_retry_delay_hours` and `callback_max_retries` are referenced in:
- `app/models/bot_config.py` (ORM columns)
- `app/models/schemas.py` (3 Pydantic schemas: Create, Update, Response)
- `app/services/queue_processor.py` (lines 418, 1040-1041)
- `frontend/src/types/api.ts` (TypeScript interface)
- `frontend/src/app/(app)/bots/[botId]/page.tsx` (form state, defaults, UI inputs)
- `app/pipeline/factory.py` (reads `callback_schedule` already — unclear usage)

Dropping these columns requires synchronized changes across all these files. If the frontend deploys before the backend migration, or vice versa, API requests will break.

**Fix**:
1. Phase the migration: first add `callback_schedule`, then update all consumers, then drop old columns in a later migration
2. Keep backward-compatible defaults: if `callback_schedule` is null, fall back to old fields
3. Document the deploy order: backend migration first, then backend code, then frontend

---

## 6. HIGH: No Validation Schema for `callback_schedule` JSONB

**Finding**: The design stores the schedule as a raw JSONB field. There's no Pydantic model defining what a valid step looks like. Bad data gets silently stored:
- `{"steps": [{"delay_hours": -5}]}` — negative delay
- `{"steps": [{"delay_hours": 3, "delay_type": "next_day"}]}` — both set (spec says mutually exclusive)
- `{"steps": [{"preferred_window": [22, 8]}]}` — window crosses midnight
- `{"steps": []}` — empty steps = no retries (is this intentional or misconfiguration?)
- `{"steps": [{"delay_hours": 0.001}]}` — effectively immediate retry
- Missing `steps` key entirely
- `preferred_window: [11]` — array with 1 element

**Fix**: Define a Pydantic model:
```python
class RetryStep(BaseModel):
    delay_hours: float | None = None  # mutually exclusive with delay_type
    delay_type: Literal["next_day"] | None = None
    preferred_window: tuple[int, int] | None = None  # [start_hour, end_hour], 0-23

    @model_validator(mode="after")
    def validate_step(self):
        if self.delay_hours is not None and self.delay_type is not None:
            raise ValueError("delay_hours and delay_type are mutually exclusive")
        if self.delay_hours is None and self.delay_type is None:
            raise ValueError("must specify delay_hours or delay_type")
        if self.delay_hours is not None and self.delay_hours < 0.5:
            raise ValueError("delay_hours must be >= 0.5")
        if self.preferred_window:
            s, e = self.preferred_window
            if not (0 <= s < 24 and 0 <= e <= 24 and s < e):
                raise ValueError("invalid preferred_window")
        return self

class CallbackSchedule(BaseModel):
    template: str | None = None
    steps: list[RetryStep]  # min 1, max 10
```

---

## 7. MEDIUM: Sequence Calls Get Auto-Retried

**Finding**: The `schedule_auto_retry` function only skips campaign calls (checks `campaign_id is not None`). Sequence calls (`source="sequence"`) are NOT excluded. If a sequence call gets `no_answer`, both the sequence engine AND `schedule_auto_retry` could schedule follow-ups, causing duplicate calls.

**Fix**: Add a guard in `schedule_auto_retry`:
```python
# Skip sequence calls — sequences have their own step logic
if original_qc and original_qc.source == "sequence":
    return
```

---

## 8. MEDIUM: Race Condition — Bot Config Changes Between Scheduling and Execution

**Finding**: Step N schedules a retry using the bot's current `callback_schedule`. By the time that retry fires (hours or a day later), the admin may have changed the schedule (e.g., removed steps, changed delays). The retry_count on the QueuedCall points to a step index that may no longer exist or have different parameters.

**Scenario**: Bot has 4 steps. Call is on retry 3 (step index 3). Admin reduces to 2 steps. Retry fires, `steps[3]` is out of bounds.

**Fix**: Two options:
1. **Snapshot at scheduling time** (recommended): Store the resolved `scheduled_at` on the QueuedCall. Don't re-read the schedule at execution time — the scheduling already happened. The current design already does this (`scheduled_at` is computed at retry creation time), so the main risk is the `max_retries` check in `_process_single_call` (line 418-419). Replace this with: "if no more steps exist at retry_count → stop" which is already the proposed logic.
2. **Store schedule snapshot in extra_vars**: Overkill for this case.

The real fix: Remove the `callback_max_retries` check in `_process_single_call` (line 418-429). With step-based scheduling, max retries is implicitly `len(steps)`. The check happens at scheduling time (no step at index = stop), not at execution time.

---

## 9. MEDIUM: `preferred_window` vs. `callback_window` Interaction

**Finding**: A step can have `preferred_window: [20, 22]` but the bot's global `callback_window_end` is `20`. The design says "if scheduled_at falls outside callback_window, push to next window opening." This means a step with `preferred_window: [20, 22]` would ALWAYS get pushed to the next day's `callback_window_start` (9 AM) — the preferred window is dead on arrival.

**Fix**: Validate at save time that all `preferred_window` ranges fall within `[callback_window_start, callback_window_end]`. Show a warning in the UI if they don't. Or: document that `callback_window` always wins and the UI should prevent creating conflicting steps.

---

## 10. MEDIUM: No Deduplication — Same Phone Can Have Multiple Pending Retries

**Finding**: If two calls to the same phone both result in `no_answer` (e.g., from different sources or a race), `schedule_auto_retry` creates a new QueuedCall each time. There's no check for "is there already a pending retry for this phone+bot?"

**Fix**: Before creating a retry QueuedCall, check:
```python
existing = await db.execute(
    select(QueuedCall).where(
        QueuedCall.bot_id == bot_id,
        QueuedCall.contact_phone == phone,
        QueuedCall.status == "queued",
        QueuedCall.source == "auto_retry",
    )
)
if existing.scalar_one_or_none():
    logger.info("retry_already_pending", phone=phone)
    return
```

---

## 11. MEDIUM: Templates Are Just Labels — No Enforcement

**Finding**: The `template` field in `callback_schedule` is a string like `"standard"`. But there's no mechanism to:
- Define what "standard" means server-side
- Prevent editing steps after selecting a template (making the label stale)
- Sync template changes to existing bots

A user selects "Standard", customizes step 2, and the label still says "Standard."

**Fix**: Either:
1. Make `template` purely informational and rename to `based_on_template` (display "Standard (modified)" in UI if steps differ from the template definition)
2. Or: make templates server-defined and immutable — `template: "standard"` means "use the server's standard definition," and `steps` is only populated for `template: "custom"`

---

## 12. LOW: Stale Processing Cleanup Could Mask Retry Bugs

**Finding**: The `_cleanup_stale_calls` function marks stale "processing" QueuedCalls as "failed" after 10 minutes. If a retry call gets stuck in processing, it becomes "failed" — and `schedule_auto_retry` only runs on `no_answer`, not `failed`. So the retry chain silently dies.

**Fix**: This is existing behavior, not introduced by this design. But worth noting: stale cleanup should log the `retry_count` and `source` so operators can detect when retry chains are dying silently.

---

## 13. LOW: No Observability for Retry Step Progression

**Finding**: The design doesn't mention logging which step was used, whether preferred_window snapping occurred, or why a retry was scheduled at a specific time. Debugging "why was this call retried at 3 AM?" requires reconstructing the logic manually.

**Fix**: Log a structured event at scheduling time:
```python
logger.info(
    "retry_step_applied",
    step_index=retry_count,
    step_config=step,
    raw_scheduled=raw_time.isoformat(),
    window_adjusted=was_adjusted,
    final_scheduled=final_time.isoformat(),
)
```

---

## 14. LOW: Frontend UX Gaps

**Finding**: The current UI has simple numeric inputs for `callback_retry_delay_hours` and `callback_max_retries`. The new design needs:
- A step builder UI (add/remove/reorder steps)
- Template selector dropdown
- Visual timeline showing when retries would fire (given a hypothetical failure time)
- Validation feedback (preferred_window outside callback_window, etc.)
- "Reset to template" button

None of this is specified in the design.

**Fix**: Add a frontend spec section covering the step builder component. At minimum: a list of step cards with delay type toggle, hours input, optional preferred window time pickers, and template preset buttons.

---

## Summary Table

| # | Severity | Issue | One-line Fix |
|---|----------|-------|-------------|
| 1 | CRITICAL | busy already maps to no_answer | Verify, remove from spec or differentiate |
| 2 | CRITICAL | Dual retry paths undefined | Spec which path gets step logic |
| 3 | HIGH | DST ambiguity in next_day | Document ZoneInfo fold behavior |
| 4 | HIGH | next_day semantics undefined | Define precisely, add minimum gap |
| 5 | HIGH | Migration drops columns still in use | Phase migration, keep backward compat |
| 6 | HIGH | No JSONB validation | Add Pydantic schema with validators |
| 7 | MEDIUM | Sequence calls get auto-retried | Add source="sequence" guard |
| 8 | MEDIUM | Config changes between schedule/execute | Remove runtime max_retries check |
| 9 | MEDIUM | preferred_window vs callback_window conflict | Validate at save time |
| 10 | MEDIUM | No dedup for same phone retries | Check for existing pending retry |
| 11 | MEDIUM | Template label becomes stale | Make informational or server-enforced |
| 12 | LOW | Stale cleanup kills retry chains silently | Log retry_count on stale cleanup |
| 13 | LOW | No observability for step progression | Add structured logging |
| 14 | LOW | Frontend spec missing | Add step builder UI spec |
