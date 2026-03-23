# Sequence Event Variable Linking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link "Relative to Event" timing on sequence steps to template datetime variables, replacing the hardcoded bot config lookup.

**Architecture:** Each step with `relative_to_event` timing stores an `event_variable` key in its `timing_value` JSONB pointing to a template variable of type `datetime`. The engine resolves event dates per-step from `context_data`, with template variable defaults merged as baseline. Auto-creates an `event_date` variable when none exists.

**Tech Stack:** FastAPI, SQLAlchemy (asyncpg), Next.js, React, Radix UI (Select component)

**Spec:** `docs/superpowers/specs/2026-03-19-sequence-event-variable-linking-design.md`

---

### Task 1: Backend — Add `parse_bot_event_date` helper and clean up imports

**Files:**
- Modify: `app/services/sequence_engine.py:1-25` (imports)
- Modify: `app/services/sequence_engine.py` (add helper function after line 30)

- [ ] **Step 1: Add `parse_bot_event_date` helper function**

In `app/services/sequence_engine.py`, after the `INTEREST_LEVELS` constant (line 25), add:

```python
def parse_bot_event_date(event_date_str: str, event_time_str: str = "") -> str | None:
    """Convert bot config free-text event_date + event_time to ISO string.

    Handles formats like "7th March 2026" + "7:30 PM".
    Returns ISO string or None if unparseable.
    """
    import re as _re
    clean = _re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", event_date_str)
    parsed = None
    for fmt in ("%d %B %Y", "%B %d %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(clean.strip(), fmt)
            break
        except ValueError:
            continue
    if not parsed:
        return None
    if event_time_str:
        for tfmt in ("%I:%M %p", "%H:%M", "%I %p"):
            try:
                t = datetime.strptime(event_time_str.strip(), tfmt)
                parsed = parsed.replace(hour=t.hour, minute=t.minute)
                break
            except ValueError:
                continue
    return parsed.isoformat()
```

- [ ] **Step 2: Remove unused imports**

In `app/services/sequence_engine.py`, remove `re` from the top-level imports (line 4) and remove `BotConfig` import (line 19). The `re` usage is now local inside `parse_bot_event_date`.

Change line 4 from:
```python
import re
```
Remove it entirely.

Change lines 18-19 from:
```python
from app.models.bot_config import BotConfig
from app.models.messaging_provider import MessagingProvider
```
to:
```python
from app.models.messaging_provider import MessagingProvider
```

- [ ] **Step 3: Commit**

```bash
git add app/services/sequence_engine.py
git commit -m "feat(sequence): add parse_bot_event_date helper, remove unused imports"
```

---

### Task 2: Backend — Refactor `create_instance` to use per-step variable resolution

**Files:**
- Modify: `app/services/sequence_engine.py:222-350` (`create_instance` function)

- [ ] **Step 1: Remove `bot_config_id` parameter**

Change the function signature (lines 222-230) from:

```python
async def create_instance(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    lead_id: uuid.UUID,
    trigger_call_id: uuid.UUID | None,
    context_data: dict,
    bot_config_id: uuid.UUID | None = None,
) -> SequenceInstance | None:
```

to:

```python
async def create_instance(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    lead_id: uuid.UUID,
    trigger_call_id: uuid.UUID | None,
    context_data: dict,
) -> SequenceInstance | None:
```

- [ ] **Step 2: Replace bot config lookup with template variable default merging**

Replace the entire block from `# Resolve event_date from bot config` through `return None` (lines 242-295) with:

```python
    # Merge template variable defaults into context_data (caller values take precedence)
    tmpl_result = await db.execute(
        select(SequenceTemplate).where(SequenceTemplate.id == template_id)
    )
    template_obj = tmpl_result.scalar_one_or_none()
    if template_obj and template_obj.variables:
        for var in template_obj.variables:
            if var.get("key") and var.get("default_value"):
                context_data.setdefault(var["key"], var["default_value"])
```

- [ ] **Step 3: Replace global event_date with per-step resolution in touchpoint loop**

Replace the touchpoint creation loop (lines ~320-349). The current code passes a single `event_date` to every step. Change to:

```python
    # Create touchpoints
    prev_scheduled = None
    for step in steps:
        # Resolve event_date per-step from context_data
        step_event_date = None
        if step.timing_type == "relative_to_event":
            event_var = step.timing_value.get("event_variable") or "event_date"
            raw = context_data.get(event_var)
            if not raw:
                logger.error(
                    "sequence_create_missing_event_variable",
                    template_id=str(template_id),
                    variable=event_var,
                )
                return None
            try:
                step_event_date = datetime.fromisoformat(str(raw))
                if step_event_date.tzinfo is None:
                    step_event_date = step_event_date.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                logger.error(
                    "sequence_create_unparseable_event_variable",
                    template_id=str(template_id),
                    variable=event_var,
                    value=str(raw),
                )
                return None

        scheduled_at = _calculate_scheduled_time(
            timing_type=step.timing_type,
            timing_value=step.timing_value,
            signup_time=now,
            event_date=step_event_date,
            prev_scheduled=prev_scheduled,
        )

        # Determine initial status
        status = "pending"
        if _should_skip(step.skip_conditions, context_data):
            status = "skipped"

        touchpoint = SequenceTouchpoint(
            instance_id=instance.id,
            step_id=step.id,
            org_id=org_id,
            lead_id=lead_id,
            step_order=step.step_order,
            step_snapshot=_snapshot_step(step),
            status=status,
            scheduled_at=scheduled_at,
            messaging_provider_id=default_provider.id if default_provider else None,
        )
        db.add(touchpoint)
        prev_scheduled = scheduled_at

    await db.flush()
    return instance
```

- [ ] **Step 4: Commit**

```bash
git add app/services/sequence_engine.py
git commit -m "feat(sequence): per-step event variable resolution in create_instance"
```

---

### Task 3: Backend — Update route handlers to pass bot config event date

> **Note:** `evaluate_trigger` also calls `create_instance` but does NOT need separate variable merging — `create_instance` now handles template variable default merging internally, so all call paths are covered.

**Files:**
- Modify: `app/plivo/routes.py:650-689`
- Modify: `app/twilio/routes.py:266-305`

- [ ] **Step 1: Update Plivo route handler**

In `app/plivo/routes.py`, update the sequence trigger block (lines 650-689). Change the `context_data` dict and remove `bot_config_id`:

```python
        # Trigger engagement sequence if bot has one configured
        if getattr(bot_config, "sequence_template_id", None) and existing_log:
            try:
                from app.services import sequence_engine
                from app.services.sequence_engine import parse_bot_event_date
                from app.models.lead import Lead
                async with get_db_session() as seq_db:
                    lead_result = await seq_db.execute(
                        select(Lead).where(
                            Lead.org_id == bot_config.org_id,
                            Lead.phone_number == existing_log.contact_phone,
                        ).limit(1)
                    )
                    lead = lead_result.scalar_one_or_none()
                    if lead and analysis:
                        ctx_data = {
                            "contact_name": lead.contact_name or "",
                            "contact_phone": lead.phone_number or "",
                            "interest_level": getattr(analysis, "interest_level", ""),
                            "goal_outcome": getattr(analysis, "goal_outcome", ""),
                            "sentiment": getattr(analysis, "sentiment", ""),
                            "call_summary": summary or "",
                        }
                        # Pass bot config event date as ISO string if available
                        if getattr(bot_config, "event_date", None):
                            iso_dt = parse_bot_event_date(
                                bot_config.event_date,
                                getattr(bot_config, "event_time", "") or "",
                            )
                            if iso_dt:
                                ctx_data["event_date"] = iso_dt
                        instance = await sequence_engine.create_instance(
                            seq_db,
                            template_id=str(bot_config.sequence_template_id),
                            org_id=bot_config.org_id,
                            lead_id=lead.id,
                            trigger_call_id=existing_log.id,
                            context_data=ctx_data,
                        )
                        if instance:
                            await seq_db.commit()
                            logger.info(
                                "sequence_triggered_post_call",
                                call_sid=call_sid,
                                instance_id=str(instance.id),
                                template_id=str(bot_config.sequence_template_id),
                            )
            except Exception as e:
                logger.error("sequence_trigger_post_call_failed", call_sid=call_sid, error=str(e))
```

- [ ] **Step 2: Update Twilio route handler**

Apply the exact same change to `app/twilio/routes.py` (lines 266-305). The code is identical.

- [ ] **Step 3: Commit**

```bash
git add app/plivo/routes.py app/twilio/routes.py
git commit -m "feat(sequence): pass bot config event_date as ISO in context_data, remove bot_config_id"
```

---

### Task 4: Frontend — Add event variable dropdown to StepCard

**Files:**
- Modify: `frontend/src/app/(app)/sequences/components/StepCard.tsx:124-132` (props interface)
- Modify: `frontend/src/app/(app)/sequences/components/StepCard.tsx:78-118` (timingSummary)
- Modify: `frontend/src/app/(app)/sequences/components/StepCard.tsx:344-349` (timing type change handler)
- Modify: `frontend/src/app/(app)/sequences/components/StepCard.tsx:401-417` (relative_to_event UI)

- [ ] **Step 1: Extend StepCardProps with new props**

In `StepCard.tsx`, update the props interface (lines 124-132):

```typescript
export interface StepCardProps {
  step: SequenceStep;
  bots: { id: string; name: string }[];
  variables: Array<{ key: string; default_value: string; description: string; type?: string }>;
  onUpdate: (stepId: string, data: Partial<SequenceStep>) => void;
  onDelete: (stepId: string) => void;
  onTestPrompt: (prompt: string, model: string) => void;
  onAddVariable: (variable: { key: string; default_value: string; description: string; type: string }) => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
}
```

Update the destructuring in the component function to include `variables` and `onAddVariable`.

- [ ] **Step 2: Update `timingSummary` to show variable name**

In `timingSummary` (lines 91-101), update the `relative_to_event` section:

```typescript
  if (step.timing_type === "relative_to_event") {
    const val = step.timing_value as Record<string, number | string>;
    const days = Number(val?.days ?? 0);
    const time = val?.time;
    const varName = val?.event_variable || "event_date";
    if (days < 0) {
      return `${Math.abs(days)}d before ${varName}${time ? ` at ${time}` : ""}`;
    } else if (days === 0) {
      return `${varName} day${time ? ` at ${time}` : ""}`;
    }
    return `${days}d after ${varName}${time ? ` at ${time}` : ""}`;
  }
```

- [ ] **Step 3: Auto-create datetime variable when "Relative to Event" is selected**

In the timing type `onValueChange` handler (lines 344-349), add auto-creation logic:

```typescript
              onValueChange={(val) => {
                setTimingType(val);
                let newTv = val === "immediate" ? {} : timingValue;
                if (val === "relative_to_event") {
                  // Auto-create event_date variable if no datetime variables exist
                  const dtVars = variables.filter((v) => v.type === "datetime");
                  if (dtVars.length === 0) {
                    onAddVariable({
                      key: "event_date",
                      type: "datetime",
                      default_value: "",
                      description: "Event date and time",
                    });
                  }
                  // Pre-select first datetime variable (or the one we just created)
                  const selectedVar = dtVars.length > 0 ? dtVars[0].key : "event_date";
                  newTv = { ...newTv, event_variable: selectedVar };
                }
                setTimingValue(newTv);
                onUpdate(step.id, { timing_type: val, timing_value: newTv });
              }}
```

- [ ] **Step 4: Add event variable dropdown to the UI**

Replace the `relative_to_event` UI section (lines 401-417) with:

```tsx
            {timingType === "relative_to_event" && (
              <>
                <Select
                  value={timingValue.event_variable || "event_date"}
                  onValueChange={(val) => {
                    const tv = { ...timingValue, event_variable: val };
                    setTimingValue(tv);
                    updateField({ timing_value: tv });
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select variable" />
                  </SelectTrigger>
                  <SelectContent>
                    {variables
                      .filter((v) => v.type === "datetime")
                      .map((v) => (
                        <SelectItem key={v.key} value={v.key}>
                          {v.key}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    placeholder="Days"
                    value={timingValue.days ?? ""}
                    onChange={(e) => {
                      const tv = { ...timingValue, days: Number(e.target.value) };
                      setTimingValue(tv);
                      updateField({ timing_value: tv });
                    }}
                    onBlur={flush}
                    className="w-full"
                  />
                  <span className="text-xs text-muted-foreground whitespace-nowrap">days (- = before)</span>
                </div>
              </>
            )}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/components/StepCard.tsx
git commit -m "feat(sequence-ui): add event variable dropdown to StepCard timing"
```

---

### Task 5: Frontend — Pass variables and callbacks from template builder page

**Files:**
- Modify: `frontend/src/app/(app)/sequences/[id]/page.tsx:501-512` (variable deletion)
- Modify: `frontend/src/app/(app)/sequences/[id]/page.tsx:414-420` (variable key rename)
- Modify: `frontend/src/app/(app)/sequences/[id]/page.tsx:556-568` (StepCard rendering)

- [ ] **Step 1: Add `onAddVariable` callback**

In the template builder page, add a callback function after `saveHeader` (after line 146):

```typescript
  const handleAddVariable = useCallback(
    (variable: { key: string; default_value: string; description: string; type: string }) => {
      // Don't add if a variable with this key already exists
      if (variables.some((v) => v.key === variable.key)) return;
      const updated = [...variables, variable];
      setVariables(updated);
      saveHeader({ variables: updated });
    },
    [variables, saveHeader],
  );
```

- [ ] **Step 2: Add variable key rename cascading**

Update the variable key `onChange` handler (lines 414-418). When a key changes, cascade-update any step's `timing_value.event_variable` that references the old key:

```typescript
                          onChange={(e) => {
                            const oldKey = variables[i].key;
                            const newKey = e.target.value;
                            const updated = [...variables];
                            updated[i] = { ...updated[i], key: newKey };
                            setVariables(updated);
                            // Cascade rename to any step referencing this variable
                            if (oldKey && oldKey !== newKey) {
                              steps.forEach((s) => {
                                if (
                                  s.timing_type === "relative_to_event" &&
                                  (s.timing_value as any)?.event_variable === oldKey
                                ) {
                                  handleUpdateStep(s.id, {
                                    timing_value: { ...s.timing_value, event_variable: newKey },
                                  });
                                }
                              });
                            }
                          }}
```

- [ ] **Step 3: Add variable deletion protection**

Update the variable delete button `onClick` (lines 506-509):

```typescript
                          onClick={() => {
                            const varKey = variables[i].key;
                            // Check if any step references this variable
                            const referencingSteps = steps.filter(
                              (s) =>
                                s.timing_type === "relative_to_event" &&
                                ((s.timing_value as any)?.event_variable === varKey ||
                                  (!((s.timing_value as any)?.event_variable) && varKey === "event_date")),
                            );
                            if (referencingSteps.length > 0) {
                              const confirm = window.confirm(
                                `This variable is used by ${referencingSteps.length} step(s) for event timing. Deleting it will break their scheduling. Continue?`,
                              );
                              if (!confirm) return;
                              // Remove event_variable from affected steps so backend default kicks in
                              referencingSteps.forEach((s) => {
                                const { event_variable, ...rest } = s.timing_value as any;
                                handleUpdateStep(s.id, { timing_value: rest });
                              });
                            }
                            const updated = variables.filter((_, idx) => idx !== i);
                            setVariables(updated);
                            saveHeader({ variables: updated });
                          }}
```

- [ ] **Step 4: Pass new props to StepCard**

Update the StepCard rendering (lines 556-568):

```tsx
                    <StepCard
                      step={step}
                      bots={bots}
                      variables={variables}
                      onUpdate={handleUpdateStep}
                      onDelete={handleDeleteStep}
                      onTestPrompt={handleTestPrompt}
                      onAddVariable={handleAddVariable}
                      isExpanded={expandedStepId === step.id}
                      onToggleExpand={() =>
                        setExpandedStepId(
                          expandedStepId === step.id ? null : step.id,
                        )
                      }
                    />
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/\[id\]/page.tsx
git commit -m "feat(sequence-ui): pass variables to StepCard, add deletion protection and key rename cascading"
```

---

### Task 6: Deploy and verify

**Files:** None (deployment only)

- [ ] **Step 1: Build frontend**

```bash
cd frontend && npm run build
```

Verify no TypeScript errors.

- [ ] **Step 2: Push and deploy backend**

```bash
git push origin main
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e --command="sudo -u root bash -c 'cd /home/animeshmahato/wavelength-v3 && git pull' && cd /home/animeshmahato/wavelength-v3 && docker compose up -d --build"
```

- [ ] **Step 3: Deploy frontend**

```bash
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e --command="cd /home/animeshmahato/wavelength-v3/frontend && pm2 restart wavelength-frontend"
```

- [ ] **Step 4: Verify — open template builder**

Open the Masterclass Engagement Sequence template in the UI. Verify:
- The `event_date` variable exists with type `datetime`
- Steps with "Relative to Event" show the event variable dropdown
- The dropdown shows `event_date` selected
- Collapsed step summaries show variable name (e.g. "3d before event_date at 19:30")

- [ ] **Step 5: Verify — trigger a test call**

Make a test call and check logs for:
- `sequence_triggered_post_call` (instance created successfully)
- No `sequence_create_missing_event_variable` errors
- Verify sequence instance exists in DB: `SELECT * FROM sequence_instances ORDER BY created_at DESC LIMIT 1`

- [ ] **Step 6: Commit any final fixes**
