# Engagement Sequence Engine — Design Spec

**Date:** 2026-03-18
**Status:** Approved
**Author:** Animesh + Claude

## Overview

A multi-tenant engagement sequence engine built into Wavelength v3 that replaces the current n8n + GHL workflow architecture. The engine supports configurable touchpoint sequences across multiple channels (WhatsApp, voice calls, SMS), AI-generated content via Claude/Anthropic, per-client credentials, and a full dashboard UI with prompt testing and JSON import/export.

## Goals

1. Replace 3 n8n workflows (Call Processor, Message Scheduler, Hope Reply Handler) with native Wavelength functionality
2. Multi-tenant from day one — different clients can define completely different sequence structures
3. Full flexibility: touchpoints, triggers (event-based, time-based, behavior-based), channels, conditions
4. Per-client WhatsApp credentials (WATI, AISensy, Twilio WhatsApp)
5. Client-editable AI prompts via dashboard with live prompt testing
6. Dashboard showing full engagement journey per lead
7. JSON import/export for sequence templates
8. Claude/Anthropic for all copywriting tasks (not Gemini)

## Non-Goals

- Real-time streaming sequence evaluation (polling at 10s is sufficient)
- Sequence pausing on manual interactions (sequences run independently)
- Intent-based reply routing (simple state-based matching only for v1)
- Email channel support (voice + WhatsApp + SMS only for v1)

---

## Data Model

### Table: `messaging_providers`

Per-org WhatsApp/SMS credentials. Same pattern as `phone_numbers` for voice.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| org_id | FK → organizations | |
| provider_type | varchar | `wati`, `aisensy`, `twilio_whatsapp`, `twilio_sms` |
| name | varchar | Display name, e.g. "My WATI Account" |
| credentials | JSONB | Fernet-encrypted at app layer (see Credentials Encryption). `{ api_url, api_token }` |
| is_default | bool | Default provider for this org |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** `(org_id)`, `(org_id, is_default)` partial where is_default=true, `(org_id, provider_type)`

---

### Table: `sequence_templates`

The configurable blueprint. Defines what a sequence looks like.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| org_id | FK → organizations | |
| bot_id | FK → bot_configs, nullable | null = org-wide template |
| name | varchar | "Masterclass Engagement" |
| trigger_type | varchar | `post_call`, `manual`, `campaign_complete` |
| trigger_conditions | JSONB | `{ goal_outcome: ["qualified"], min_interest: "medium" }` |
| max_active_per_lead | int, default 1 | Prevents multiple instances of same template for one lead |
| is_active | bool | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** `(org_id)`, `(bot_id, is_active)`
**Constraints:** `UNIQUE(org_id, name)` — prevent duplicate template names per org

---

### Table: `sequence_steps`

Touchpoint definitions within a template. Each step is one action in the sequence.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| template_id | FK → sequence_templates | RESTRICT delete (see Template Versioning) |
| step_order | int | 1, 2, 3... |
| name | varchar | "gift", "hope", "call2" |
| is_active | bool, default true | Temporarily disable a step without deleting |
| channel | varchar | `whatsapp_template`, `whatsapp_session`, `voice_call`, `sms` |
| timing_type | varchar | `relative_to_signup`, `relative_to_event`, `relative_to_previous_step` |
| timing_value | JSONB | `{ hours: 1 }` or `{ days: -1, time: "18:30" }` |
| skip_conditions | JSONB, nullable | `{ field: "attended_saturday", equals: "yes" }` |
| content_type | varchar | `static_template`, `ai_generated`, `voice_call` |
| whatsapp_template_name | varchar, nullable | Meta-approved template name |
| whatsapp_template_params | JSONB, nullable | Param mapping: `[{ name: "1", value: "{{contact_name}}" }]` |
| ai_prompt | text, nullable | Claude prompt with `{{variable}}` placeholders |
| ai_model | varchar, nullable | `claude-sonnet`, `claude-haiku` |
| voice_bot_id | FK → bot_configs, nullable | Which bot for voice call steps |
| expects_reply | bool, default false | True for hope-style steps |
| reply_handler | JSONB, nullable | `{ action: "ai_respond", ai_prompt: "...", save_field: "hope_statement" }` |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** `(template_id, step_order)` unique

---

### Table: `sequence_instances`

A running sequence for a specific lead.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| org_id | FK → organizations | |
| template_id | FK → sequence_templates | |
| lead_id | FK → leads | |
| trigger_call_id | FK → call_logs, nullable | The call that triggered this sequence |
| status | varchar | `active`, `completed`, `paused`, `cancelled` |
| context_data | JSONB | All variables for content generation: `{ contact_name, profession, challenge, event_date, event_time, masterclass_link, anchor_task, tried_ai, ... }` |
| started_at | timestamptz | |
| completed_at | timestamptz, nullable | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** `(lead_id)`, `(org_id, status)`, `(template_id, status)`
**Constraints:** `UNIQUE(template_id, lead_id) WHERE status = 'active'` — prevents duplicate active instances at DB level

---

### Table: `sequence_touchpoints`

Each scheduled delivery — the execution log. This is what the dashboard queries.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| instance_id | FK → sequence_instances | CASCADE delete |
| step_id | FK → sequence_steps, SET NULL on delete | Nullable — if step deleted after touchpoint created |
| org_id | FK → organizations | Denormalized for tenant isolation in scheduler |
| lead_id | FK → leads, SET NULL on delete | Denormalized for fast queries |
| step_order | int | Denormalized |
| step_snapshot | JSONB | Snapshot of step config at creation time (see Template Versioning) |
| status | varchar | `pending`, `generating`, `scheduled`, `sent`, `failed`, `skipped`, `awaiting_reply`, `replied` |
| scheduled_at | timestamptz | When this touchpoint should fire |
| generated_content | text, nullable | AI-generated copy or resolved template params |
| sent_at | timestamptz, nullable | |
| session_window_expires_at | timestamptz, nullable | WhatsApp 24hr window expiry (set on template send) |
| error_message | text, nullable | |
| reply_text | text, nullable | What the lead replied |
| reply_response | text, nullable | What we sent back |
| retry_count | int, default 0 | |
| max_retries | int, default 2 | |
| messaging_provider_id | FK → messaging_providers, nullable | |
| queued_call_id | FK → call_queue, nullable | For voice call steps |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** `(instance_id, step_order)`, `(lead_id, status)`, `(org_id, status, scheduled_at)` — last one is critical for the scheduler query

---

## Backend Services

### `app/services/anthropic_client.py`

Lightweight Claude API wrapper for copywriting tasks.

```
AnthropicClient:
  - generate_content(prompt: str, variables: dict, model: str = "claude-sonnet") → str
      Interpolates {{variables}} into prompt, calls Claude API, returns generated text.

  - test_prompt(prompt: str, sample_variables: dict, model: str) → dict
      Same as generate_content but returns { content, tokens_used, latency_ms, cost_estimate }.
      Powers the prompt testing UI.
```

- Variable interpolation: `{{profession}}` in prompt → replaced from `context_data` before sending
- Models: `claude-sonnet` → `claude-sonnet-4-20250514`, `claude-haiku` → `claude-haiku-4-5-20251001`
- Max tokens configurable per step, default 300

### `app/services/messaging_client.py`

Multi-provider WhatsApp/SMS delivery.

```
MessagingClient:
  - send_template(provider_config: dict, phone: str, template_name: str, params: list) → { success, message_id, error }
  - send_session_message(provider_config: dict, phone: str, text: str) → { success, message_id, error }
  - send_sms(provider_config: dict, phone: str, text: str) → { success, message_id, error }
```

- Factory pattern: reads `provider_type`, dispatches to WATI/AISensy/Twilio handler
- Same pattern as voice telephony (Plivo vs Twilio resolved at runtime)
- Each handler implements the same interface, provider-specific API differences hidden

### `app/services/sequence_engine.py`

Core orchestration logic.

```
SequenceEngine:
  - evaluate_trigger(db, bot_id, call_analysis, lead, call_log) → Optional[SequenceInstance]
      Called after every completed call. Checks if any active template's trigger_conditions
      match the call outcome. If yes, creates instance + all touchpoints with calculated times.

  - create_instance(db, template_id, lead_id, trigger_call_id, context_data) → SequenceInstance
      Creates instance + all touchpoints. Timing calculated per step:
        - relative_to_signup: now + timing_value
        - relative_to_event: event_date ± timing_value
        - relative_to_previous_step: previous_step.scheduled_at + timing_value
      Skip conditions evaluated at creation time where possible (some deferred to execution).

  - process_touchpoint(db, touchpoint) → None
      The workhorse. For each due touchpoint:
        1. Re-check skip_conditions against instance.context_data
        2. If AI content needed: call anthropic_client.generate_content()
        3. Route to channel:
           - whatsapp_template → messaging_client.send_template()
           - whatsapp_session → messaging_client.send_session_message()
           - voice_call → create QueuedCall via callback_scheduler pattern
           - sms → messaging_client.send_sms()
        4. Update touchpoint status (sent / awaiting_reply / failed)
        5. If last step and all sent → mark instance as completed

  - handle_reply(db, phone, message_text) → None
      Finds touchpoint: status="awaiting_reply", lead matched by normalized phone,
      most recent first, within 48-hour reply window.
      If multiple sequences awaiting reply from same phone, matches most recent touchpoint.
      Checks session_window_expires_at — if expired, skips session message (logs warning).
      If reply_handler.action == "ai_respond":
        - Generate response via Claude with reply_handler.ai_prompt
        - Send via whatsapp_session (only if within 24hr window)
        - Save reply_text + reply_response on touchpoint
        - Save to instance.context_data[reply_handler.save_field] (available to subsequent steps)
        - Optionally save to lead.custom_fields[reply_handler.save_field]
      Update touchpoint status to "replied".
```

### `app/services/sequence_scheduler.py`

Background poller — runs as asyncio task in app lifespan.

```
SequenceScheduler:
  - start() → asyncio task
  - poll_interval: 10 seconds
  - query: SELECT touchpoints WHERE status IN ("pending", "scheduled") AND scheduled_at <= now()
  - uses SELECT...FOR UPDATE SKIP LOCKED (same as queue_processor)
  - processes touchpoints in batches with asyncio.gather (max 10 concurrent)
  - uses raw SQL with FOR UPDATE SKIP LOCKED (same pattern as queue_processor.py line 314, not ORM)
  - for each due touchpoint: calls sequence_engine.process_touchpoint()
  - on failure: increments retry_count, reschedules or marks failed
  - on permanent failure (retry_count >= max_retries): marks "failed", logs alert
```

### Post-call hook

In `app/plivo/routes.py`, after analysis + lead sync (~line 620):

```python
# Trigger engagement sequence if matching template exists
await sequence_engine.evaluate_trigger(db, bot_id, analysis, lead, call_log)
```

One line addition. Same pattern as `_run_ghl_workflows()` that already exists there.

### WhatsApp reply webhook

New route `app/api/webhooks.py`:

```
POST /api/webhooks/whatsapp-reply/{provider_id}
  - Provider ID in URL identifies which messaging_provider config to use for HMAC verification
  - Verifies webhook signature (WATI HMAC / AISensy signature)
  - Parses phone + message text (provider-specific format)
  - Normalizes phone number (reuse existing normalize_phone_india pattern)
  - Deduplicates by message_id (ignore if already processed — providers may retry webhooks)
  - Calls sequence_engine.handle_reply()
  - Returns 200 OK
```

---

## API Endpoints

### Template Management — `app/api/sequences.py`

```
GET    /api/sequences/templates                    — List org's templates
POST   /api/sequences/templates                    — Create template
GET    /api/sequences/templates/{id}               — Get template with all steps
PUT    /api/sequences/templates/{id}               — Update template
DELETE /api/sequences/templates/{id}               — Soft delete (deactivate)

POST   /api/sequences/templates/{id}/steps         — Add step
PUT    /api/sequences/steps/{id}                   — Update step
DELETE /api/sequences/steps/{id}                   — Remove step
POST   /api/sequences/templates/{id}/reorder       — Reorder steps (accepts array of step IDs)
```

### Prompt Testing

```
POST   /api/sequences/test-prompt
  Body: { prompt: str, variables: dict, model: "claude-sonnet" | "claude-haiku" }
  Returns: { generated_content: str, tokens_used: int, latency_ms: int, cost_estimate: float }
```

Pure preview — no side effects. Rate-limited to 20 calls/hour per org to control Claude API costs.

### Instance Monitoring

```
GET    /api/sequences/instances                    — List with filters (lead_id, template_id, status, date range). Paginated (limit/offset, same as /api/leads)
GET    /api/sequences/instances/{id}               — Instance detail with all touchpoints
POST   /api/sequences/instances/{id}/pause         — Pause running sequence
POST   /api/sequences/instances/{id}/resume        — Resume paused sequence
POST   /api/sequences/instances/{id}/cancel        — Cancel sequence
```

### Touchpoint Detail

```
GET    /api/sequences/touchpoints/{id}             — Full detail (content, reply, errors)
POST   /api/sequences/touchpoints/{id}/retry       — Retry a failed touchpoint
```

### JSON Import/Export

```
GET    /api/sequences/templates/{id}/export        — Full template + steps as JSON
POST   /api/sequences/templates/import             — Create template + steps from JSON
POST   /api/sequences/templates/import/preview     — Validate JSON, return parsed preview (dry run)
```

**Export JSON format:**
```json
{
  "name": "Masterclass Engagement",
  "trigger_type": "post_call",
  "trigger_conditions": { "goal_outcome": ["qualified"] },
  "steps": [
    {
      "name": "gift",
      "step_order": 1,
      "channel": "whatsapp_template",
      "timing_type": "relative_to_signup",
      "timing_value": { "hours": 1 },
      "content_type": "ai_generated",
      "whatsapp_template_name": "ai_career_gift",
      "whatsapp_template_params": [
        { "name": "1", "value": "{{contact_name}}" },
        { "name": "2", "value": "{{profession}}" }
      ],
      "ai_prompt": "Generate a 3-point AI career action plan...",
      "ai_model": "claude-sonnet",
      "expects_reply": false
    }
  ]
}
```

Import validates: required fields, valid channel/timing/content_type enums, AI prompt has matching variables, step_order is sequential. Preview endpoint returns validation errors or parsed template for confirmation.

### Messaging Providers

```
GET    /api/messaging/providers                    — List org's providers
POST   /api/messaging/providers                    — Add provider
PUT    /api/messaging/providers/{id}               — Update credentials
DELETE /api/messaging/providers/{id}               — Remove provider
POST   /api/messaging/providers/{id}/test          — Send test message to verify connection
```

---

## Frontend UI

### 1. Sequence Templates Page — `/dashboard/sequences/templates`

- Table: template name, trigger type, step count, active toggle, created date
- Actions: create new, import JSON, click row to edit
- Import: file upload or paste JSON → preview → confirm

### 2. Template Builder — `/dashboard/sequences/templates/{id}`

- **Header**: template name, trigger type dropdown, trigger conditions editor, active toggle
- **Steps list**: vertical, drag-to-reorder
- Each step is an expandable card:
  - Name field
  - Channel selector: WhatsApp Template / WhatsApp Session / Voice Call / SMS
  - Timing config: type dropdown + value inputs (hours/days/time)
  - Skip conditions: optional, field + operator + value
  - Content section (varies by content_type):
    - `whatsapp_template`: template name + param mapping table
    - `ai_generated`: prompt textarea with `{{variable}}` highlighting + **"Test Prompt" button**
    - `voice_call`: bot selector dropdown from org's bots
  - Reply handler toggle: expects reply? → response prompt textarea + save_field input
- **Export JSON** button in header
- **Add Step** button at bottom

### 3. Prompt Test Panel — Slide-over within template builder

- Left: prompt text with highlighted `{{variables}}`
- Right: sample variables form (auto-populated from context_data keys, editable)
- Model selector: Claude Sonnet / Haiku
- "Generate" button → shows: generated output, tokens used, cost estimate, latency
- "Try Again" button for regeneration
- History of last 5 test runs for comparison

### 4. Engagement Monitor — `/dashboard/sequences/monitor`

- Filters: template, status (active/completed/paused/cancelled), date range
- Table columns: lead name, phone, template, current step, next touchpoint time, status
- Click row → expands touchpoint timeline:
  - Each step as a card: step name, channel icon, scheduled time, status badge
  - Sent: generated content preview, delivery timestamp
  - Reply: their message + our response
  - Failed: error message + retry button
  - Pending: countdown to scheduled time

### 5. Lead Detail Integration — existing `/dashboard/leads/{id}`

- New "Sequences" tab alongside call history
- Shows all sequence instances for this lead
- Same touchpoint timeline as monitor page

### 6. Messaging Providers — `/dashboard/settings/messaging`

- Similar to existing telephony settings page
- Table: provider name, type (WATI/AISensy/Twilio), status, default badge
- Add/edit provider: type dropdown, credentials form (API URL, token), name
- Test connection button (sends test message)
- Set as default toggle

---

## GHL Integration Changes

GHL becomes a **one-way sync target**, not the data store:

- **Keep**: `post_ghl_outcome()` — pushes call results to GHL (already exists)
- **Keep**: `ghl_workflows` tagging — triggers GHL automations (already exists)
- **Add**: After sequence completes, optionally tag contact in GHL (e.g., "engagement_complete")
- **Remove**: All 24 custom fields for engagement tracking in GHL
- **Remove**: All 3 n8n workflows

GHL stays as the CRM view. Wavelength owns the data and orchestration.

---

## Migration Strategy

1. Build the engine + API + scheduler
2. Import the current masterclass sequence as the first template (via JSON import)
3. Run both systems in parallel for one batch (n8n + Wavelength) to verify
4. Kill n8n workflows once verified
5. Remove GHL custom fields for engagement

---

## Technical Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| LLM for copywriting | Claude (Anthropic) | Better creative writing, tone, empathy than Gemini |
| LLM for real-time voice | Gemini 2.5 Flash | Low latency, streaming (unchanged) |
| LLM for post-call analysis | Gemini 2.5 Flash | Structured extraction, already works (unchanged) |
| Scheduling mechanism | Async polling (10s) | Matches existing pattern, no new infra needed |
| WhatsApp delivery | Per-org provider credentials | Multi-tenant, same pattern as voice telephony |
| Sequence state | Dedicated tables | Dashboard needs queryable rows, not JSONB blobs |
| Reply routing | State-based matching | Simple, reliable, no AI classification overhead |
| Sequence vs manual interaction | Independent | Sequences run regardless of manual interactions |

---

## Credentials Encryption

Messaging provider credentials are encrypted at the application layer using **Fernet symmetric encryption** (from the `cryptography` library, already a transitive dependency).

- Encryption key: `MESSAGING_CREDENTIALS_KEY` env var (Fernet key, 32-byte base64)
- Encrypt on write (POST/PUT provider), decrypt on read (when sending messages)
- Stored in Postgres as encrypted JSONB string, not plaintext
- Same approach can be retrofitted to existing telephony credentials later
- Key rotation: generate new key, re-encrypt all providers in a migration

This matches industry standard for app-level secret storage without requiring a vault service.

---

## Template Versioning

When a sequence instance is created, each touchpoint gets a `step_snapshot` (JSONB) containing the full step configuration at that moment. This snapshot is what the scheduler uses for execution — not the live step definition.

**Rules:**
- Editing a template step only affects **future** instances. Running instances use their snapshots.
- Deleting a step: `step_id` FK is SET NULL. Touchpoints with snapshots continue to work.
- Reordering steps: only affects future instances. Running touchpoints keep their original `step_order`.
- Disabling a step (`is_active=false`): future instances skip it. Running instances unaffected.

This is the "snapshot at creation" approach — simple, no version table needed, and safe for concurrent editing.

---

## Concurrency Control

**Multiple sequences per lead:**
- `evaluate_trigger` checks: does this lead already have an active instance of this template?
- If `template.max_active_per_lead` (default 1) is reached, skip creating a new instance.
- Different templates CAN run concurrently for the same lead (e.g., "Masterclass Engagement" + "Upsell Sequence").
- Same template cannot have multiple active instances per lead unless explicitly configured.

**WhatsApp rate limiting:**
- The scheduler spaces touchpoints for the same phone number at least 60 seconds apart to avoid provider throttling.
- If two sequences fire WhatsApp to the same lead within a window, the second is delayed by 60s.

---

## WhatsApp Session Window Handling

The WhatsApp Business API has a 24-hour session window: after sending a template message, you can send free-form session messages for 24 hours from the user's last reply.

**Implementation:**
- When a template message is sent, set `session_window_expires_at = now() + 24 hours` on the touchpoint.
- When a reply comes in, the window resets: update `session_window_expires_at = now() + 24 hours`.
- `handle_reply` checks `session_window_expires_at` before sending a session message.
- If window expired: log a warning, do NOT send. The touchpoint status stays `awaiting_reply` with a note.
- Dashboard shows window status: "Session active (Xh remaining)" or "Session expired".

---

## Event Date Handling

The `relative_to_event` timing type requires an event date in `context_data`.

**Rules:**
- Expected key: `event_date` (ISO 8601 format, e.g., `"2026-03-21"`)
- Optional: `event_time` (e.g., `"19:30"`) — used for same-day timing
- Validation at instance creation: if any step uses `relative_to_event` but `context_data` has no `event_date`, instance creation fails with a clear error.
- Timezone: all times stored in UTC, converted using org's timezone setting (existing pattern).

---

## Voice Call Step Completion

When a `voice_call` step creates a `QueuedCall`:
- The touchpoint's `queued_call_id` is set to the created call's ID
- Status set to `scheduled` (not `sent` — call hasn't happened yet)
- In the existing post-call handler (`plivo/routes.py`), after call completion:
  - Check if the call's `queued_call_id` matches any touchpoint
  - If found: update touchpoint status to `sent`, set `sent_at`
  - This is a 3-line addition to the existing post-call flow

---

## Content Type Clarification

The `content_type` field determines how content is prepared and sent:

| content_type | What happens |
|---|---|
| `static_template` | WhatsApp template params are interpolated from `context_data` using `{{variable}}` syntax. No AI involved. Sent via `send_template()`. |
| `ai_generated` | Claude generates the content using `ai_prompt` + `context_data`. The output can be: (a) sent as a session message directly, or (b) used as a template parameter value if `whatsapp_template_name` is also set. When both are present, AI generates the text and it's injected into the template param. |
| `voice_call` | Creates a `QueuedCall` for the specified `voice_bot_id`. No text content generated. |

---

## Failure Alerting

When a touchpoint permanently fails (retry_count >= max_retries):
- Touchpoint status set to `failed`
- Dashboard shows a badge/count of failed touchpoints on the Engagement Monitor page
- Failed touchpoints are highlighted in red on the touchpoint timeline
- Manual retry button available per touchpoint
- Future: webhook notification to org (not in v1)

---

## Pause/Resume Semantics

When a sequence is paused:
- All pending touchpoints keep their original `scheduled_at` times
- The scheduler skips touchpoints belonging to paused instances
- On resume: touchpoints whose `scheduled_at` has passed fire immediately (within next poll cycle)
- Touchpoints whose `scheduled_at` is still in the future fire at original time

This is "absolute time" semantics — simple to implement, predictable behavior.

---

## Billing Integration

- **Claude API costs**: Deducted from org's credit balance. Each `generate_content` call records tokens used. Cost calculated at current Anthropic pricing and debited via new `bill_ai_usage()` function (separate from existing `bill_completed_call`, not a rename).
- **Prompt testing**: Also deducted from credits (same rate). The 20/hour rate limit provides a safety net.
- **WhatsApp/SMS delivery**: Provider costs are external (WATI/AISensy billing is separate). Not tracked in Wavelength credits for v1.
- **Voice call steps**: Already billed through existing call billing system.
