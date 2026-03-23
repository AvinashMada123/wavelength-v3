# Sequence Flow Builder — Current State Analysis

## Current Architecture Summary

Sequences today are **linear step lists** — Step 1 → Step 2 → Step 3 — with no branching based on outcomes.

---

## Backend Models (4 tables)

### SequenceTemplate
- Template definitions with `trigger_type` (post_call, manual, campaign_complete)
- Trigger conditions: goal_outcome & min_interest filtering
- `max_active_per_lead` prevents duplicate enrollments

### SequenceStep
- Linear `step_order` (1, 2, 3...)
- **Channels**: `voice_call`, `whatsapp_template`, `whatsapp_session`, `sms`
- **Timing**: `relative_to_signup`, `relative_to_event`, `relative_to_previous_step`
- **Content types**: `ai_generated`, `template`, `static`
- Basic `skip_conditions` (field equality checks) — only way to "branch" today
- WhatsApp template params with variable interpolation
- AI prompt with context variable injection

### SequenceInstance
- Enrollment of a lead in a template
- Status: `active`, `paused`, `cancelled`, `completed`
- `context_data` carries call analysis, lead info, captured data

### SequenceTouchpoint
- Execution record for each step per instance
- Status lifecycle: `pending` → `generating` → `scheduled` → `sending` → `sent` → `awaiting_reply` → `replied`
- Retry: `retry_count` / `max_retries` (default 2)
- Tracks `generated_content`, `reply_text`, `reply_response`

---

## Backend Services

### Sequence Engine (661 lines)
- `evaluate_trigger()` — Post-call auto-enrollment based on call analysis
- `create_instance()` — Creates all touchpoints upfront with pre-calculated schedules
- `process_touchpoint()` — Executes: AI generation → send via channel
- `handle_reply()` — WhatsApp reply processing with optional AI auto-response
- `_should_skip()` — Simple field equality skip conditions
- `_calculate_scheduled_time()` — Timing relative to signup/event/previous step

### Sequence Scheduler (163 lines)
- Polls every 10s for due touchpoints
- Max 10 concurrent per batch
- Retries failed touchpoints every 5th cycle
- 60s phone spacing for WhatsApp rate limiting

---

## Frontend

### Pages
- `/sequences` — Template list (CRUD, import/export)
- `/sequences/[id]` — Template editor with step cards, drag-to-reorder
- `/sequences/monitor` — Live instance monitoring with touchpoint timeline
- `/sequences/analytics` — Dashboard with funnel, channels, failures

### Components
- **StepCard** — Channel, timing, content preview
- **TouchpointTimeline** — Status-colored timeline with retry buttons
- **SequencesTab** — Lead page integration showing active sequences

---

## Critical Gaps & Edge Cases

### 1. No Branching / Conditional Flow
- Steps execute linearly regardless of outcome
- `skip_conditions` is the only "branching" — skip a step if field matches
- **No way to say**: "If call not picked up → send WhatsApp, else → do nothing"
- **No way to say**: "If replied positively → schedule callback, else → send follow-up"

### 2. Call Outcome Handling
- Sequences trigger only AFTER call completion (`evaluate_trigger`)
- If a call isn't picked up, the sequence doesn't trigger at all
- Voice touchpoints create QueuedCall but don't track pickup/no-answer outcome
- **No feedback loop**: call outcome doesn't influence next step

### 3. Retry Logic is Basic
- Fixed max retries, no exponential backoff
- No distinction between "no answer", "busy", "failed to connect"
- Retries happen on scheduler cycle (immediate, not delayed)
- No configurable retry intervals

### 4. All Touchpoints Created Upfront
- `create_instance()` pre-creates ALL touchpoints at enrollment
- Future touchpoints can't adapt based on earlier outcomes
- Schedule is fixed — can't dynamically add/remove steps

### 5. WhatsApp Limitations
- No message delivery status tracking (read receipts, delivery confirmation)
- Session window (24hr) silently expires awaiting_reply touchpoints
- No fallback if template message fails

### 6. No Wait/Delay Nodes
- Timing is step-to-step only
- No "wait until business hours" or "wait for reply up to X hours then proceed"

### 7. No External Event Triggers
- Can't react to: lead opens email, visits website, fills form
- Only triggers: post_call, manual, campaign_complete

---

## What Needs to Change for Flow Builder

| Current | Needed |
|---------|--------|
| Linear step list | DAG (directed acyclic graph) with branches |
| `step_order` integer | Node positions + edge connections |
| Pre-created touchpoints | Dynamic touchpoint creation at branch points |
| `skip_conditions` | Outcome-based routing (picked up/not picked up/etc.) |
| Fixed retries | Configurable retry with delay and max attempts |
| No call outcome feedback | Call status webhooks feeding back into flow |
| List-based UI | Visual canvas with drag-and-drop nodes |
| Steps only | Nodes: action, condition, delay, trigger |

---

## Files That Will Be Affected

**Backend:**
- `app/models/sequence.py` — New models for nodes, edges, flow definitions
- `app/services/sequence_engine.py` — Major rewrite for graph traversal
- `app/services/sequence_scheduler.py` — Adapt for dynamic node execution
- `app/api/sequences.py` — New endpoints for flow CRUD

**Frontend:**
- `frontend/src/app/(app)/sequences/[id]/page.tsx` — Replace with flow canvas
- `frontend/src/lib/sequences-api.ts` — New types for nodes/edges
- New: Flow canvas component, node components, edge rendering
