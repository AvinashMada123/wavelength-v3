# Sequence Flow Builder — Design Audit Against Existing Backend

**Date:** 2026-03-23
**Auditor:** Claude (automated)
**Files examined:** `app/models/sequence.py`, `app/services/sequence_engine.py`, `app/services/sequence_scheduler.py`, `app/api/sequences.py`, `app/models/lead.py`, `app/pipeline/runner.py`, `app/plivo/routes.py`, `app/services/anthropic_client.py`, `app/models/call_queue.py`, `app/services/messaging_client.py`, `app/models/call_log.py`

---

## 1. BLUNDERS — Things That Won't Work

### 1.1 No call-outcome feedback loop to sequence touchpoints (CRITICAL)
The design assumes Condition nodes can branch on call outcome (picked up / no answer / busy / failed). **This feedback loop does not exist.** When `sequence_engine.process_touchpoint()` queues a voice call, it sets the touchpoint status to `"scheduled"` and creates a `QueuedCall` — but there is **no code anywhere** that updates the touchpoint status after the call completes.

- `app/plivo/routes.py` `plivo_event()` handles hangup callbacks but **never looks up or updates** the corresponding `SequenceTouchpoint`. It triggers `evaluate_trigger()` (to start *new* sequences) and `schedule_auto_retry()`, but ignores any in-flight touchpoint.
- `app/services/queue_processor.py` has `finalize_campaign_call()` and `schedule_auto_retry()` — neither references `SequenceTouchpoint`.
- **Impact:** Voice call touchpoints remain stuck in `"scheduled"` status forever. The sequence never advances past a call step. The design's entire conditional branching on call outcomes is built on infrastructure that doesn't exist.
- **Fix required before flow builder:** Add a callback in `plivo_event()` that: (1) looks up `QueuedCall.extra_vars.sequence_touchpoint_id`, (2) updates the touchpoint with call outcome, (3) triggers next-node evaluation.

### 1.2 "Publish migrates ALL leads to new version" is destructive
The design says publishing migrates all active leads to the new flow version. This is dangerous:
- Current model has `SequenceInstance.context_data` storing step-specific state. A structural graph change could orphan leads mid-flow.
- No versioning exists on `SequenceTemplate` — there's no `version` column, no `published_at`, no `draft_flow_data` vs `published_flow_data`.
- A lead that was on step 3 of a linear sequence has no meaningful mapping to "node X" of a completely restructured graph.
- **Fix:** Version the flow definition (store `flow_data` JSONB with a version counter). Active instances should pin to the version they started on. Only new enrollments get the latest version.

### 1.3 Plivo status mapping loses detail the design needs
`_map_plivo_status()` in `plivo/routes.py` collapses `busy`, `timeout`, and `no-answer` all into `"no_answer"`. The design wants distinct `picked_up / no_answer / busy / failed` outcomes. The current mapping destroys the `busy` distinction.

---

## 2. MISSING INFRASTRUCTURE

### 2.1 No graph/flow storage model
Current model: `SequenceStep` with `step_order` integer (linear). The flow builder needs:
- `flow_data: JSONB` on `SequenceTemplate` storing nodes + edges (React Flow format)
- `SequenceNode` table (or embedded in JSONB) replacing `SequenceStep`
- `current_node_id` on `SequenceInstance` or `SequenceTouchpoint` for graph traversal

### 2.2 No graph traversal engine
`sequence_engine.py` is entirely linear: `create_instance()` pre-creates ALL touchpoints with calculated times at enrollment. A flow builder requires:
- On-demand next-node resolution after each node completes
- Edge evaluation (condition checking) at runtime
- Dynamic touchpoint creation (only create the next touchpoint, not all upfront)

### 2.3 No business hours system
`grep -r "business_hours\|BusinessHours\|time_window"` returns zero results. The design assumes configurable time windows per node and org-level defaults. None of this exists — it needs:
- `business_hours` JSONB on Organization model
- Per-node override field
- Scheduler awareness to delay execution outside windows

### 2.4 No WhatsApp delivery status tracking
`messaging_client.py` fires and forgets — `DeliveryResult` has `message_id` but it's never stored on the touchpoint. There are no WhatsApp status webhooks configured. The design's Condition node branching on "reply received" works (via `handle_reply()`), but branching on "delivered" / "read" / "failed delivery" is impossible.

### 2.5 No simulation/dry-run infrastructure
The design proposes visual dry-run and live test modes. Nothing exists for this — it's pure greenfield.

### 2.6 No "Goal Met" milestone tracking
The design has a "Goal Met" node that marks a milestone without ending the flow. There's no concept of goals/milestones in the current model. Needs a `goals_met: JSONB[]` on `SequenceInstance`.

### 2.7 No "Wait for Event" infrastructure
The design proposes waiting for external events (e.g., "lead replies on WhatsApp", "lead books a call"). The current `handle_reply()` only handles WhatsApp replies. There's no generic event bus or webhook listener that could feed into flow nodes.

### 2.8 No multi-flow coordination
The design mentions `max_active_per_lead` to prevent over-contact. This field exists on `SequenceTemplate` but is scoped per-template. Cross-flow coordination (e.g., "don't call this lead if another flow called them today") doesn't exist.

---

## 3. MIGRATION RISKS

### 3.1 SequenceStep → Node migration
- `SequenceStep` has `step_order` with a unique constraint `(template_id, step_order)`. This must be dropped for graph nodes.
- `SequenceTouchpoint` references `step_id` (FK to `sequence_steps`) and `step_order`. Both become meaningless in a graph model.
- **Migration path:** Add `node_id` column to touchpoints, keep `step_id` nullable for backward compat, deprecate after migration.

### 3.2 Pre-created touchpoints → dynamic creation
Current engine pre-creates ALL touchpoints at enrollment time (`create_instance()` lines 266-373). Flow builder needs lazy/on-demand creation. Active instances with pre-created pending touchpoints need handling during migration.

### 3.3 API breakage
Every endpoint in `app/api/sequences.py` assumes linear steps:
- `POST /templates/{id}/steps` — step CRUD with `step_order`
- `PUT /templates/{id}/steps/reorder` — linear reordering
- Step test endpoint assumes single step execution
- All response schemas (`StepResponse`, `TouchpointResponse`) are step-oriented
- **These all break.** New endpoints needed: `PUT /templates/{id}/flow` (save graph), `GET /templates/{id}/flow` (load graph).

### 3.4 Frontend complete rewrite
The existing `TemplateBuilderPage` and `StepCard` components are entirely linear-step-based. The flow builder is a complete replacement, not an enhancement.

---

## 4. COMPATIBILITY ISSUES

### 4.1 Bot config retries conflict
The design says "Bot config retries still work outside flows, overridden inside flows." Currently `schedule_auto_retry()` in `queue_processor.py` runs unconditionally on `no_answer`. If a flow already has retry logic, the bot-level retry will fire too, causing duplicate calls. The flow engine must signal to `plivo_event()` that this call is flow-managed.

### 4.2 Sequence trigger fires at wrong time for flow builder
`evaluate_trigger()` runs in `plivo_event()` and creates instances with all touchpoints pre-scheduled. For flow builder, the trigger should only create an instance at the start node — subsequent nodes are created dynamically.

### 4.3 Anthropic client is compatible
`generate_content()` accepts `prompt`, `variables`, `model`, `max_tokens`, `org_id`, `reference`. This works for the AI Generate + Send node with no changes. The `_interpolate_variables()` helper is reusable.

### 4.4 WhatsApp session window tracking works
`session_window_expires_at` on touchpoints already tracks the 24-hour WhatsApp session window. This is reusable for the WhatsApp Session node type.

---

## 5. MISSING FROM THE DESIGN

### 5.1 No error handling / dead letter strategy
What happens when a node fails after max retries? The design has no "Error" terminal node or error routing. In a linear sequence, a failed touchpoint just stops — in a flow, it could block the entire graph.

### 5.2 No concurrency control for parallel branches
If the flow builder supports parallel paths (fan-out after a condition), what prevents two branches from calling the same lead simultaneously? The current scheduler has phone spacing (60s gap) but only for WhatsApp, not voice.

### 5.3 No flow-level timeout
Individual "Wait for Event" nodes have timeouts, but there's no overall flow timeout. A lead could be stuck in a flow indefinitely if they hit a path with no terminal node.

### 5.4 No audit trail for node transitions
The design mentions "canvas journey replay" for leads, but there's no `flow_transitions` table to record "lead X moved from node A to node B at time T because condition C evaluated to true." Without this, replay is impossible.

### 5.5 No rate limiting strategy for AI Generate nodes
Each AI Generate node calls Anthropic. In a flow with multiple AI nodes, a batch of 1000 leads hitting an AI node simultaneously would hammer the API. The design doesn't mention batching or rate limiting.

### 5.6 No handling of lead removal from active flows
The design says "Deleting node with active leads requires removing them first" but doesn't specify what "removing" means — pause the instance? Complete it? Move leads to a different node?

### 5.7 No webhook/external trigger for "Wait for Event"
The design lists "Wait for Event" but doesn't specify how external events arrive. There's no webhook endpoint for external systems to post events that resolve a waiting node.

---

## 6. WHAT'S SALVAGEABLE

| Component | Verdict | Notes |
|---|---|---|
| `SequenceTemplate` model | **Extend** | Add `flow_data: JSONB`, `version: int`, `status: draft/published` |
| `SequenceInstance` model | **Extend** | Add `current_node_id`, `flow_version`, `goals_met: JSONB` |
| `SequenceTouchpoint` model | **Extend** | Add `node_id`, keep `step_id` nullable for migration |
| `sequence_engine.evaluate_trigger()` | **Reuse** | Trigger logic works, just change instance creation to start at entry node |
| `sequence_engine._matches_trigger_conditions()` | **Reuse** | Condition evaluation logic, extend for new field types |
| `sequence_engine.process_touchpoint()` | **Partial rewrite** | Channel-specific send logic is reusable; scheduling/advancement logic must change |
| `sequence_engine.handle_reply()` | **Reuse** | WhatsApp reply handling works as-is |
| `sequence_scheduler.py` | **Major rewrite** | Must change from "poll pending touchpoints" to "poll pending + evaluate next node" |
| `anthropic_client.py` | **Reuse as-is** | `generate_content()` and `_interpolate_variables()` fully compatible |
| `messaging_client.py` | **Reuse as-is** | All send methods work; add delivery status webhooks separately |
| `QueuedCall` model | **Reuse as-is** | `extra_vars` already carries `sequence_touchpoint_id` |
| `CallLog` model | **Reuse as-is** | Has `status`, `outcome`, `metadata_` with analysis data |
| API routes | **Rewrite** | Linear step CRUD → graph CRUD; instance/touchpoint queries adaptable |
| Frontend | **Rewrite** | Linear editor → React Flow canvas; lead timeline is new |

---

## Priority Fix Order

1. **Call outcome feedback loop** — Without this, neither the current linear engine nor the flow builder can branch on call results. This is a standalone fix independent of the flow builder.
2. **Flow data model** — Add `flow_data` JSONB, versioning columns, `node_id` on touchpoints.
3. **Graph traversal engine** — Replace linear advancement with edge-based next-node resolution.
4. **Business hours** — Org-level + per-node time windows.
5. **Node transition audit trail** — Required for analytics and journey replay.
6. **WhatsApp delivery status webhooks** — Required for delivery-based conditions.
