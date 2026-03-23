# Sequence Event Variable Linking

## Problem

"Relative to Event" timing on sequence steps has no way to specify which event datetime to be relative to. The backend was hardcoded to look at `bot_config.event_date` (a free-text field like "7th March 2026"), which required fragile parsing and tightly coupled sequences to bot configs. The template defined an `event_date` variable but it was never connected to the timing system.

## Design Decisions

- **Step-level variable reference**: Each step with `relative_to_event` timing stores which template variable it references. Different steps can reference different datetime variables.
- **Only `datetime` type variables**: The event variable must be type `datetime` (not date-only). The step's time picker in timing config overrides the variable's time component when scheduling.
- **Auto-create on first use**: When a user selects "Relative to Event" and no `datetime` variable exists, auto-create one named `event_date` and pre-select it.
- **Template variables are source of truth**: No bot config lookup. Event datetime flows through `context_data` like any other variable.
- **Backward compatibility**: Existing steps without `event_variable` in their `timing_value` default to `"event_date"` via `.get("event_variable", "event_date")`.

## Data Model

### `sequence_steps.timing_value` (JSONB)

When `timing_type = "relative_to_event"`, add `event_variable` key:

```json
{
  "days": -3,
  "time": "19:30",
  "event_variable": "event_date"
}
```

No migration needed — JSONB, just a new key.

### `sequence_templates.variables` (JSONB array)

No structural change. Referenced variable must have `type: "datetime"`. Default value stored as ISO string from `datetime-local` input (e.g. `"2026-03-22T19:30"`). Both `"2026-03-22T19:30"` and `"2026-03-22T19:30:00"` are valid — `datetime.fromisoformat()` handles both.

## Frontend Changes

### StepCard (`StepCard.tsx`)

When `relative_to_event` is selected, render a dropdown of datetime variables between the timing type selector and days input:

```
[Relative to Event v]  [event_date v]  [-3] days (- = before)  [07:30 PM]
```

The dropdown lists all template variables with `type: "datetime"`.

**Auto-create flow:**
1. User selects "Relative to Event" as timing type
2. StepCard checks template variables for any with `type: "datetime"`
3. If none found: call parent callback to add `{ key: "event_date", type: "datetime", default_value: "", description: "Event date and time" }` to template variables and save
4. Pre-select `event_date` in dropdown, save `timing_value.event_variable = "event_date"`

**New props on StepCard:**
- `variables: TemplateVariable[]` — template variables from parent, for populating the dropdown
- `onAddVariable: (variable: TemplateVariable) => void` — callback to auto-create a variable

**Variable deletion protection:** When deleting a template variable, check if any step's `timing_value.event_variable` references it. If so, show a confirmation warning: "This variable is used by step(s) X. Deleting it will break their event timing." Allow deletion but clear `event_variable` on affected steps.

**Variable key rename:** When a variable key is renamed, cascade-update any step's `timing_value.event_variable` that references the old key.

**Collapsed step summary:** Update `timingSummary` to include the variable name when `relative_to_event`, e.g. "3d before event_date at 19:30" instead of "3d before event at 19:30".

### Template Builder Page (`[id]/page.tsx`)

- Pass `variables` and an `onAddVariable` callback as props to each StepCard
- `onAddVariable` adds the variable to state, saves header, returns the updated list

### Template Variables Section

No changes — already supports `datetime` type with `datetime-local` picker.

## Backend Changes

### `sequence_engine.py` — `create_instance`

Remove:
- `bot_config_id` parameter
- Bot config lookup block (template → bot_id → BotConfig → parse free-text date)
- `BotConfig` import
- `re` import

Add template variable default merging into `context_data`:

```python
# Load template to get variable defaults
template = ...  # already loading for bot_id check, repurpose
if template and template.variables:
    for var in template.variables:
        if var.get("key") and var.get("default_value"):
            context_data.setdefault(var["key"], var["default_value"])
```

Replace global event_date resolution with per-step resolution in the touchpoint creation loop:

```python
for step in steps:
    event_date = None
    if step.timing_type == "relative_to_event":
        event_var = step.timing_value.get("event_variable", "event_date")
        raw = context_data.get(event_var)
        if not raw:
            logger.error("sequence_create_missing_event_variable",
                         template_id=str(template_id), variable=event_var)
            return None
        try:
            event_date = datetime.fromisoformat(str(raw))
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.error("sequence_create_unparseable_event_variable",
                         template_id=str(template_id), variable=event_var, value=str(raw))
            return None

    scheduled_at = _calculate_scheduled_time(
        timing_type=step.timing_type,
        timing_value=step.timing_value,
        signup_time=now,
        event_date=event_date,
        prev_scheduled=prev_scheduled,
    )
```

### `evaluate_trigger` — also needs variable defaults

`evaluate_trigger` in `sequence_engine.py` is another call path that creates instances. It builds its own `context_data` from call analysis. After building context_data, merge template variable defaults before calling `create_instance`:

```python
# After building context_data from analysis...
# Merge template variable defaults (context_data values take precedence)
if template.variables:
    for var in template.variables:
        if var.get("key") and var.get("default_value"):
            context_data.setdefault(var["key"], var["default_value"])
```

This ensures event datetime variables with defaults are available even through this path.

### `_calculate_scheduled_time`

No change. Already receives `event_date` as datetime parameter.

### Route Handlers (`plivo/routes.py`, `twilio/routes.py`)

Simplify context_data construction — no need to load template variables here since `create_instance` now handles merging defaults:

```python
context_data = {
    "contact_name": lead.contact_name or "",
    "contact_phone": lead.phone_number or "",
    "interest_level": getattr(analysis, "interest_level", ""),
    "goal_outcome": getattr(analysis, "goal_outcome", ""),
    "sentiment": getattr(analysis, "sentiment", ""),
    "call_summary": summary or "",
}
# If bot_config has event_date + event_time, combine into ISO string
# This overrides the template variable default if both exist
if getattr(bot_config, "event_date", None):
    from app.services.sequence_engine import parse_bot_event_date
    iso_dt = parse_bot_event_date(bot_config.event_date, getattr(bot_config, "event_time", ""))
    if iso_dt:
        context_data["event_date"] = iso_dt
```

Add a helper `parse_bot_event_date` to `sequence_engine.py` that handles the free-text → ISO conversion (moved from `create_instance`). This is a transitional helper — once bot configs use proper datetime fields, it can be removed.

Remove `bot_config_id=bot_config.id` from `create_instance` call.

## Variable Resolution Order

1. **Template variable default value** — baseline (set via datetime picker in template builder)
2. **Caller-provided context_data** — overrides defaults (bot config event date, call analysis data)

Merging happens inside `create_instance` via `context_data.setdefault()`, so callers always win.

Priority: caller > template default. If neither provides a value for a required event variable, `create_instance` logs the missing variable name and returns None.

## Files Changed

| File | Change |
|------|--------|
| `app/services/sequence_engine.py` | Remove bot config lookup, add template variable default merging, per-step event variable resolution, remove `bot_config_id` param, add `parse_bot_event_date` helper |
| `app/plivo/routes.py` | Use `parse_bot_event_date` to pass bot config event date in context_data, remove `bot_config_id` |
| `app/twilio/routes.py` | Same as plivo routes |
| `frontend/src/app/(app)/sequences/components/StepCard.tsx` | Add event variable dropdown, auto-create logic, new props |
| `frontend/src/app/(app)/sequences/[id]/page.tsx` | Pass variables + onAddVariable to StepCard, variable deletion protection, key rename cascading |
