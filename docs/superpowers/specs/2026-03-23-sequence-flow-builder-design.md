# Sequence Flow Builder — Design Spec

> **Status:** Draft
> **Date:** 2026-03-23
> **Author:** Claude + Animesh

## 1. Overview

Replace the linear step-based sequence system with a visual flow builder. Users design flows on a drag-and-drop canvas (React Flow), connecting nodes that represent actions (calls, messages), conditions (branch on outcomes), and control logic (delays, waits). Flows execute as directed acyclic graphs (DAGs) with exclusive branching — one path at a time per lead.

### Goals
- Visual, intuitive flow design for non-technical coaches
- Branch on call outcomes (picked up, no answer, busy, failed) and post-call analysis (interest, sentiment, goal)
- Simulate flows before going live (dry-run + live test)
- Full traceability — replay any lead's journey through a flow
- Backward compatible — existing linear sequences auto-migrate

### Non-Goals (v1)
- Parallel branch execution (fan-out/fan-in)
- External event triggers beyond current set (post_call, manual, campaign_complete)
- Document generation node (Phase 2)
- SMS channel
- Cross-flow awareness / coordination

---

## 2. Prerequisites (Build First)

These are independent of the flow builder UI and should be built before or in parallel with the flow engine.

### 2.1 Call Outcome Feedback Loop

**Problem:** `plivo_event()` updates `CallLog` but never closes the loop back to sequence touchpoints. `QueuedCall.extra_vars` carries `sequence_touchpoint_id` but nothing reads it after call completion.

**Solution:**
- In `plivo_event()`, after updating `CallLog`, check `extra_vars` for `sequence_touchpoint_id`
- Update the corresponding touchpoint with the call outcome
- Write a `FlowEvent` record (see §3.3) so the flow engine can pick it up
- Map Plivo statuses to normalized enum: `picked_up`, `no_answer`, `busy`, `failed`, `voicemail`
- Store both raw Plivo status and normalized enum — never collapse granularity

### 2.2 Plivo Status Granularity

**Problem:** Current `_map_plivo_status()` collapses `busy`, `timeout`, `no-answer` into a single value.

**Solution:**
- New enum: `CallOutcome` = `picked_up | no_answer | busy | timeout | failed | voicemail | unknown`
- Store raw Plivo `CallStatus` alongside normalized `CallOutcome`
- Condition nodes branch on `CallOutcome`

### 2.3 Business Hours System

- Org-level default: configurable working hours (e.g., Mon–Sat 9AM–7PM IST)
- Per-node override: each action node can set its own send window or toggle "send anytime"
- When an action is scheduled outside the window → defer to next valid window
- Stored as `business_hours` JSON on `Organization` model + `send_window` on `FlowNode.config`

### 2.4 Rate Limiting (Persistent)

**Problem:** Current 60s phone-spacing is in-memory, resets each scheduler batch.

**Solution:**
- New table or Redis key: `LeadContactLog(lead_id, org_id, channel, contacted_at)`
- Enforce at scheduler level before executing any action node:
  - Per-lead daily cap: max 5 actions/day (org-configurable)
  - Per-lead hourly cap: max 2 actions/hour
  - Per-lead cooldown: min 60s between any two actions
- When cap hit → action stays queued for next available window, not dropped
- Exposed in org settings for configuration

---

## 3. Data Model

### 3.1 FlowDefinition

Replaces the concept of a "template" for flow-based sequences. Existing `SequenceTemplate` stays for backward compatibility during migration.

```
FlowDefinition:
  id: UUID (PK)
  org_id: UUID (FK → Organization)
  name: String
  description: String (optional)
  trigger_type: Enum(post_call, manual, campaign_complete)
  trigger_conditions: JSONB (goal_outcome, min_interest filters)
  max_active_per_lead: Integer (default 1)
  variables: JSONB (template variables)
  is_active: Boolean
  created_at, updated_at: Timestamp
```

### 3.2 FlowVersion

Immutable published snapshots. Leads are pinned to the version they enrolled on. Once a version is published, its nodes and edges are frozen — the API rejects mutations to non-draft versions.

```
FlowVersion:
  id: UUID (PK)
  flow_id: UUID (FK → FlowDefinition)
  version_number: Integer (auto-increment per flow)
  status: Enum(draft, published, archived)
  is_locked: Boolean (default false — set to true on publish, prevents node/edge mutations)
  published_at: Timestamp (nullable)
  published_by: UUID (FK → User, nullable)
  created_at: Timestamp
```

### 3.3 FlowNode

Tenant scoping: `org_id` is denormalized here (matching the existing pattern on `SequenceStep`) for efficient RLS and direct queries without joining through FlowVersion → FlowDefinition.

```
FlowNode:
  id: UUID (PK)
  version_id: UUID (FK → FlowVersion)
  org_id: UUID (FK → Organization)
  node_type: Enum(
    voice_call, whatsapp_template, whatsapp_session, ai_generate_send,
    condition, delay_wait, wait_for_event,
    goal_met, end
  )
  name: String (user-facing label)
  position_x: Float (canvas position)
  position_y: Float (canvas position)
  config: JSONB (node-type-specific configuration, see §4)
  created_at: Timestamp
```

### 3.4 FlowEdge

```
FlowEdge:
  id: UUID (PK)
  version_id: UUID (FK → FlowVersion)
  org_id: UUID (FK → Organization)
  source_node_id: UUID (FK → FlowNode)
  target_node_id: UUID (FK → FlowNode)
  condition_label: String (e.g., "picked_up", "no_answer", "timeout", "default")
  sort_order: Integer (evaluation priority for condition edges)
```

### 3.5 FlowInstance

Replaces `SequenceInstance` for flow-based sequences.

```
FlowInstance:
  id: UUID (PK)
  org_id: UUID (FK → Organization)
  flow_id: UUID (FK → FlowDefinition)
  version_id: UUID (FK → FlowVersion) — pinned at enrollment
  lead_id: UUID (FK → Lead)
  trigger_call_id: UUID (FK → CallLog, nullable)
  status: Enum(active, paused, completed, cancelled, error)
  current_node_id: UUID (FK → FlowNode, nullable)
  context_data: JSONB (lead info, call analysis, captured data)
  error_message: String (nullable)
  is_test: Boolean (default false) — live test instances
  started_at, completed_at: Timestamp
  created_at, updated_at: Timestamp
```

**Migration coexistence note:** The existing `SequenceInstance` table gets a new `engine_type` column (default: `linear`). `FlowInstance` is a separate table used only by the flow engine. The scheduler checks `SequenceInstance.engine_type` for legacy routing, and polls `FlowInstance` for flow-based execution. Two separate tables, not a discriminator on one table.

### 3.6 FlowTouchpoint

Execution record for each node visit. Extends the concept of `SequenceTouchpoint`.

```
FlowTouchpoint:
  id: UUID (PK)
  instance_id: UUID (FK → FlowInstance)
  node_id: UUID (FK → FlowNode)
  org_id: UUID (FK → Organization)
  lead_id: UUID (FK → Lead)
  node_snapshot: JSONB (frozen copy of node config at execution time)
  status: Enum(pending, executing, waiting, completed, failed, skipped)
  scheduled_at: Timestamp
  executed_at: Timestamp (nullable)
  completed_at: Timestamp (nullable)
  outcome: String (nullable — e.g., "picked_up", "no_answer", "replied", "timed_out")
  generated_content: Text (nullable)
  error_message: String (nullable)
  retry_count: Integer (default 0)
  max_retries: Integer (default 2)
  messaging_provider_id: String (nullable)
  queued_call_id: UUID (FK → call_queue.id, nullable)
```

**Indexes:**
- `(instance_id)` — journey replay queries
- `(org_id, status, scheduled_at)` — scheduler polling (matches existing SequenceTouchpoint pattern)
- `(lead_id, org_id)` — lead profile flow history

### 3.7 FlowTransition

Audit trail for journey replay and debugging.

```
FlowTransition:
  id: UUID (PK)
  instance_id: UUID (FK → FlowInstance)
  from_node_id: UUID (FK → FlowNode, nullable — null for entry)
  to_node_id: UUID (FK → FlowNode)
  edge_id: UUID (FK → FlowEdge, nullable)
  outcome_data: JSONB (what triggered this transition)
  transitioned_at: Timestamp
```

### 3.8 FlowEvent

Event delivery mechanism for "Wait for Event" nodes.

```
FlowEvent:
  id: UUID (PK)
  instance_id: UUID (FK → FlowInstance)
  event_type: Enum(call_completed, reply_received, timeout, manual_advance)
  event_data: JSONB
  consumed: Boolean (default false)
  created_at: Timestamp
```

The scheduler polls for unconsumed events matching waiting touchpoints. Webhooks (Plivo, WhatsApp) write events; the engine consumes them.

**Cleanup policy:** Consumed events are deleted after 30 days by a periodic cleanup task. Unconsumed events older than 7 days are flagged for review (likely orphaned from cancelled instances).

---

## 4. Node Configuration Schemas

### 4.1 Voice Call
```json
{
  "bot_id": "uuid",
  "quick_retry": {
    "enabled": true,
    "max_attempts": 3,
    "interval_hours": 1
  },
  "send_window": {
    "enabled": true,
    "start": "09:00",
    "end": "19:00",
    "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
    "timezone": "Asia/Kolkata"
  }
}
```
**Outgoing edges:** `picked_up`, `no_answer`, `busy`, `timeout`, `failed`, `voicemail`
After `picked_up`, post-call analysis is available for downstream condition nodes.

When `quick_retry.enabled`: the node internally retries on `no_answer`/`busy` up to `max_attempts` with `interval_hours` delay. Only after exhausting retries does it emit the `no_answer`/`busy` edge. If retries are disabled, the outcome edge fires immediately.

Bot config retries are **ignored** for calls triggered by flow nodes.

### 4.2 WhatsApp Template
```json
{
  "template_name": "string",
  "template_params": {
    "1": "{{contact_name}}",
    "2": "{{ai_content}}"
  },
  "ai_param_generation": {
    "enabled": false,
    "param_key": "2",
    "prompt": "Generate a personalized follow-up message for {{contact_name}}..."
  },
  "send_window": { ... }
}
```
**Outgoing edges:** `sent`, `failed`

### 4.3 WhatsApp Session
```json
{
  "message": "string (static)" | null,
  "ai_generation": {
    "enabled": true,
    "prompt": "...",
    "model": "claude-sonnet-4-6"
  },
  "on_window_expired": "fallback_template" | "expired_branch",
  "fallback_template_name": "string (if on_window_expired = fallback_template)",
  "expects_reply": true,
  "reply_handler": {
    "action": "ai_respond" | "capture_field",
    "ai_prompt": "...",
    "capture_field_name": "string"
  },
  "send_window": { ... }
}
```
**Outgoing edges:** `sent`, `replied`, `expired`, `failed`

If `on_window_expired = "fallback_template"`: automatically sends the fallback template, then follows `sent` edge.
If `on_window_expired = "expired_branch"`: follows the `expired` edge, user wires the fallback in the flow.

### 4.4 AI Generate + Send
```json
{
  "mode": "fill_template_vars" | "full_message",
  "prompt": "Generate a message for {{contact_name}} who is a {{profession}}...",
  "model": "claude-sonnet-4-6",
  "send_via": "whatsapp_session" | "whatsapp_template",
  "template_name": "string (if send_via = whatsapp_template)",
  "template_param_key": "string (which param to fill)",
  "send_window": { ... }
}
```
**Outgoing edges:** `sent`, `failed`

### 4.5 Condition
```json
{
  "conditions": [
    {
      "label": "interested",
      "rules": [
        { "field": "interest_level", "operator": "gte", "value": 7 }
      ]
    },
    {
      "label": "callback_requested",
      "rules": [
        { "field": "goal_outcome", "operator": "eq", "value": "callback" }
      ]
    }
  ],
  "default_label": "other"
}
```
**Outgoing edges:** One per condition label + default. Evaluated top-to-bottom, first match wins (exclusive branching).

Available fields for conditions:
- `call_outcome`: picked_up, no_answer, busy, failed, voicemail
- `interest_level`: 1-10 from call analysis
- `goal_outcome`: from call analysis
- `sentiment`: positive, neutral, negative
- `reply_text`: content of WhatsApp reply (for contains/regex matching)
- Any field from `context_data` or lead record

### 4.6 Delay / Wait
```json
{
  "duration_value": 2,
  "duration_unit": "hours" | "minutes" | "days",
  "send_window": {
    "enabled": true,
    "resume_at": "09:00",
    "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
    "timezone": "Asia/Kolkata"
  }
}
```
**Outgoing edges:** `completed` (single edge, always fires after delay)

If `send_window.enabled` and delay expires outside window → waits until next valid window.

### 4.7 Wait for Event
```json
{
  "event_type": "reply_received" | "call_completed",
  "timeout_hours": 24,
  "timeout_label": "timed_out"
}
```
**Outgoing edges:** The event type label (e.g., `reply_received`, `call_completed`) + `timed_out`

Mechanism: When the node activates, a touchpoint is created with status `waiting`. The scheduler checks for matching `FlowEvent` records. If timeout expires with no event → follows timeout edge.

### 4.8 Goal Met
```json
{
  "goal_name": "booking_confirmed",
  "goal_description": "Lead has confirmed their coaching session booking"
}
```
**Outgoing edges:** Single `continue` edge. Goal is recorded on the instance but flow proceeds.

### 4.9 End
```json
{
  "end_reason": "completed" | "disqualified" | "unresponsive"
}
```
**Outgoing edges:** None. Marks instance as completed.

---

## 5. Flow Engine

### 5.1 Graph Traversal

```
on node_completed(instance, node, outcome):
  1. Record FlowTransition(from=node, outcome)
  2. Update FlowTouchpoint status → completed, set outcome
  3. Get outgoing edges from node, sorted by sort_order
  4. Evaluate each edge's condition_label against outcome
  5. First match → transition to target node
     No match → check for "default" edge → follow it
     No default → mark instance as error("no matching edge")
  6. Activate target node:
     - Create FlowTouchpoint(status=pending)
     - If action node → schedule based on send_window + rate limits
     - If control node → evaluate immediately
     - If terminal node → handle completion/goal
  7. Update instance.current_node_id
```

### 5.2 Error Handling on Action Nodes

Every action node follows this policy:
1. On failure → increment `retry_count`
2. If `retry_count < max_retries` → re-schedule with backoff (retry_count * 5 minutes)
3. If `retry_count >= max_retries` → emit `failed` edge
4. Every action node MUST have a `failed` outgoing edge (enforced by validation)
5. If no `failed` edge wired → validation warning, auto-connect to End node with `end_reason=failed`

### 5.3 Admin Notifications

- When an instance enters `error` status → notify org admins (in-app notification + optional email)
- When a flow's error rate exceeds 10% over 1 hour → alert notification
- Dashboard widget showing flows with active errors

### 5.4 Scheduler Adaptation

The scheduler handles both linear and flow instances during migration:

```
Two polling loops running in parallel:
  1. SequenceInstance (engine_type=linear) → process with existing sequence_engine.py
  2. FlowInstance + FlowTouchpoint → process with new flow_engine.py
```

For flow instances, the scheduler:
1. Polls `FlowTouchpoint` where `status=pending` and `scheduled_at <= now()`
2. Checks rate limits (persistent `LeadContactLog`)
3. Checks business hours / send windows
4. Executes the action
5. On completion/failure → calls `node_completed()` to traverse

For "Wait for Event" nodes:
1. Polls `FlowEvent` where `consumed=false` and matches a `waiting` touchpoint
2. On match → consume event, call `node_completed()` with event data
3. Also checks timeout: `waiting` touchpoints past timeout → emit timeout edge

---

## 6. Flow Validation

Before a flow version can be published, validate:

### Errors (block publish)
- Every node is reachable from the entry point
- Every path eventually reaches an End node (no dead ends)
- No cycles without a Delay/Wait node in the loop (prevents instant infinite loops)
- Condition nodes have at least 2 outgoing edges
- All action nodes have required config fields filled
- All action nodes have a `failed` edge (or accept auto-wiring to End)
- No disconnected subgraphs

### Warnings (allow publish, show to user)
- Unused outgoing edges on condition nodes
- Very short delays (< 5 minutes) in retry loops
- Flows with no Goal Met nodes
- Nodes with identical config (possible duplicates)

### Structural Rules
- **Exclusive branching only (v1):** Each node has exactly one active outgoing path at runtime. No fan-out to parallel branches.
- **Convergence allowed on control/terminal nodes only (v1):** Multiple branches may merge into Delay, Condition, Goal Met, or End nodes — but NOT into action nodes (Voice Call, WhatsApp, AI Generate). This prevents ambiguous execution state while avoiding the need for every branch to duplicate downstream logic. Since branching is exclusive (only one path active at a time), `current_node_id` remains a single value even with convergence.

---

## 7. Draft / Publish Model

### Workflow
1. Create flow → auto-creates FlowVersion v1 with `status=draft`
2. Edit nodes/edges on draft version freely
3. Click "Publish" → validation runs → if passed, version status → `published`, flow is live
4. Edit again → creates new draft version (v2), copying nodes/edges from published version
5. Publish v2 → v1 status → `archived`, v2 → `published`

### Version Pinning
- When a lead enrolls, `FlowInstance.version_id` is set to the current published version
- Lead continues on that version even if a new version is published
- Manual "re-enroll" action: cancel current instance, create new instance on latest published version
- Bulk re-enroll available from flow management UI

### Deleting Nodes in Draft
- If editing a draft that copies from a published version, deleting a node only affects the draft
- Active leads on the published version are unaffected
- On publish, the old version is archived — active leads on it continue until completion

---

## 8. Simulation & Testing

### 8.1 Visual Dry-Run
- Click "Simulate" on canvas toolbar
- Select or create a mock lead profile (name, phone, interest level, etc.)
- Flow highlights the entry node
- At each action node: shows what would be sent (message preview, call config)
- At each condition node: user picks the outcome or system auto-evaluates from mock data
- Path lights up green as the simulation progresses
- At End/Goal: shows summary of the simulated journey
- No messages sent, no data persisted. Pure client-side visualization.

### 8.2 Live Test Mode
- Click "Live Test" → enter your phone number
- Creates a real `FlowInstance` with `is_test=true` flag
- **Delay compression:** All delays compressed by configurable ratio (default: 1 hour → 1 minute, 1 day → 10 minutes). Configurable in test settings.
- Real calls and messages go out to the test number
- Test instances clearly marked in monitor view, excluded from analytics
- Can cancel at any time

### 8.3 Journey Replay
- On the canvas, open "Leads" panel (sidebar/drawer)
- Shows all leads currently in this flow with their status and current node
- Click a lead → their actual path highlights on the canvas
- Each visited node shows: timestamp, outcome, generated content (if any)
- Transition arrows show time elapsed between nodes
- Failed/error nodes highlighted in red with error message

---

## 9. Frontend Architecture

### 9.1 Tech Stack
- **React Flow (`@xyflow/react`)** — canvas, nodes, edges, zoom/pan
- **Existing stack:** Next.js 16 + React 19 + shadcn/ui + Tailwind + Radix
- React Flow is compatible with `"use client"` pattern already used throughout
- No SSR issues — canvas pages are client-only components

### 9.2 Pages

| Route | Purpose |
|-------|---------|
| `/sequences` | Flow list (replaces template list). CRUD, search, filter, clone. |
| `/sequences/[id]` | **Flow canvas** — the main builder. Node palette sidebar, canvas, properties panel. |
| `/sequences/[id]/simulate` | Dry-run simulation view (canvas in read-only + simulation controls). |
| `/sequences/monitor` | Instance monitoring — reuse existing with flow-aware columns. |
| `/sequences/analytics` | Analytics — adapt existing + per-node drill-down. |

### 9.3 Canvas Components

```
FlowCanvas (main container)
├── NodePalette (left sidebar — draggable node types by category)
├── ReactFlowCanvas (center — nodes + edges)
│   ├── VoiceCallNode
│   ├── WhatsAppTemplateNode
│   ├── WhatsAppSessionNode
│   ├── AIGenerateNode
│   ├── ConditionNode
│   ├── DelayWaitNode
│   ├── WaitForEventNode
│   ├── GoalMetNode
│   └── EndNode
├── PropertiesPanel (right sidebar — selected node config)
├── CanvasToolbar (top — undo/redo, zoom, simulate, publish, test)
└── LeadsPanel (bottom drawer — leads in flow, journey replay)
```

### 9.4 UX Guardrails

**Auto-layout (default):**
- Top-down structured layout using dagre or ELK layout algorithm
- Nodes snap to grid
- Edges auto-route (avoid overlaps)
- Toggle to free-form positioning for power users

**Flow templates:**
- On "Create New Flow" → show template picker:
  - "Blank flow" — just a start + end node
  - "Post-call follow-up" — call → condition (interested?) → WhatsApp or retry
  - "No-answer recovery" — call → no answer → WhatsApp → delay → retry call
  - "Lead nurture" — condition on interest → AI personalized messages → delay → follow-up
- Templates are pre-built FlowVersions with placeholder config

**Undo/Redo:**
- Full undo/redo stack for canvas operations (add/delete/move nodes, add/delete edges, config changes)
- Ctrl+Z / Ctrl+Y (Cmd on Mac)
- Undo stack persists within the editing session

**Keyboard shortcuts:**
- `Delete` / `Backspace` — delete selected node(s)/edge(s)
- `Ctrl+C` / `Ctrl+V` — copy/paste nodes
- `Ctrl+A` — select all
- `Ctrl+Z` / `Ctrl+Y` — undo/redo
- `Space` + drag — pan canvas

**Guided tour:**
- First-time user tooltip tour on canvas open
- Highlights: node palette, canvas area, properties panel, publish button
- Dismissible, shown once per user

**Desktop only:**
- Canvas is desktop-only (min-width: 1024px)
- Mobile shows a read-only flow summary (list view of nodes) with a prompt to use desktop for editing

### 9.5 Reusable Existing Components
- `PromptTestPanel` — AI prompt testing, reuse as-is
- Analytics page — adapt queries for flow structure
- Monitor page — extend with flow-specific columns
- `ImportExportDialog` — adapt for flow JSON format

---

## 10. Lead Integration

### 10.1 Lead Profile — Flow History Tab
New tab on lead detail page alongside existing tabs:
- Chronological list of all flow enrollments
- Each entry shows: flow name, version, status, enrolled date, completed date
- Expandable to show node-by-node journey with timestamps and outcomes
- Click "View on Canvas" → opens flow canvas with this lead's journey highlighted

### 10.2 Manual Lead Management
- **Enroll:** From lead profile or from flow canvas, manually add a lead to a flow
- **Remove:** Remove a lead from an active flow (sets instance to `cancelled`)
- **Re-enroll:** Cancel current instance, create new on latest published version
- **Bulk operations:** Select multiple leads in leads list → enroll/remove from flow

### 10.3 Canvas Leads Panel
- Drawer/sidebar on flow canvas showing leads currently in this flow
- Filter by: status (active, completed, error), current node
- Click a lead → journey replay (see §8.3)
- Shows count badges per node on the canvas (e.g., "47 leads here")

---

## 11. Analytics

### 11.1 Canvas Badges
Each node on the canvas shows a small badge:
- **Action nodes:** `{passed} / {failed}` with success rate percentage
- **Condition nodes:** Count per branch (e.g., "picked_up: 89 | no_answer: 23")
- **Goal nodes:** Total goals achieved
- **End nodes:** Total completions
- Badges refresh on page load (not real-time to avoid performance issues)

### 11.2 Analytics Page
Adapt existing analytics page with flow-specific metrics:
- **Funnel view:** Drop-off at each node in the most common path
- **Conversion rate:** Leads enrolled → leads reaching Goal Met
- **Node performance:** Time spent at each node, failure rates
- **Channel breakdown:** Messages sent by channel, delivery rates
- **Comparison:** Side-by-side version performance (v1 vs v2)

---

## 12. API Endpoints

### New Flow Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/flows` | List flows (paginated, filterable) |
| POST | `/api/flows` | Create flow |
| GET | `/api/flows/{id}` | Get flow with current draft/published version |
| PUT | `/api/flows/{id}` | Update flow metadata |
| DELETE | `/api/flows/{id}` | Delete flow (if no active instances) |
| GET | `/api/flows/{id}/versions` | List versions |
| GET | `/api/flows/{id}/versions/{vid}` | Get version with nodes + edges |
| POST | `/api/flows/{id}/versions` | Create new draft version |
| PUT | `/api/flows/{id}/versions/{vid}` | Atomic graph save: accepts `{nodes: [...], edges: [...]}` payload. Replaces all nodes/edges in the draft version in a single transaction. This is the primary save mechanism for the canvas. |
| POST | `/api/flows/{id}/versions/{vid}/publish` | Validate + publish |
| POST | `/api/flows/{id}/clone` | Duplicate flow |

### Node/Edge Operations (within draft version)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/flows/{id}/versions/{vid}/nodes` | Add node |
| PUT | `/api/flows/{id}/versions/{vid}/nodes/{nid}` | Update node |
| DELETE | `/api/flows/{id}/versions/{vid}/nodes/{nid}` | Delete node |
| POST | `/api/flows/{id}/versions/{vid}/edges` | Add edge |
| DELETE | `/api/flows/{id}/versions/{vid}/edges/{eid}` | Delete edge |
| PUT | `/api/flows/{id}/versions/{vid}/layout` | Bulk update node positions |
| POST | `/api/flows/{id}/versions/{vid}/validate` | Run validation without publishing |

### Instance Management
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/flows/{id}/instances` | List instances |
| GET | `/api/flows/instances/{iid}` | Get instance with touchpoints + transitions |
| POST | `/api/flows/{id}/enroll` | Enroll lead(s) |
| POST | `/api/flows/instances/{iid}/cancel` | Cancel instance |
| POST | `/api/flows/instances/{iid}/pause` | Pause instance |
| POST | `/api/flows/instances/{iid}/resume` | Resume instance |
| POST | `/api/flows/instances/{iid}/reenroll` | Cancel + re-enroll on latest version |

### Simulation
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/flows/{id}/versions/{vid}/simulate` | Dry-run: accepts `{mock_lead: {...}, outcomes: {node_id: "outcome"}}`. Returns `{path: [{node_id, node_type, action_preview, outcome}], goals_hit: [...], end_reason}` |
| POST | `/api/flows/{id}/live-test` | Start live test with phone number |

### Existing Endpoints (kept during migration)
All `/api/sequences/*` endpoints remain functional for `engine_type=linear` instances.

---

## 13. Migration Strategy

### Phase 1: Coexistence
1. Add `engine_type` column to `SequenceInstance` (default: `linear`) for legacy routing
2. Deploy new `FlowInstance` / `FlowTouchpoint` tables alongside existing tables
3. Scheduler runs two parallel polling loops: one for `SequenceInstance` (linear engine), one for `FlowInstance` (flow engine)
4. New flows use flow engine with new tables. Existing sequences continue on linear engine with existing tables.

### Phase 2: Auto-Convert
1. Script to convert existing `SequenceTemplate` → `FlowDefinition` + `FlowVersion`
2. Steps become a linear chain: Node1 → Node2 → ... → End
3. `skip_conditions` become Condition nodes
4. Converted flows are created as drafts for review before publishing

### Phase 3: Deprecate
1. Once all linear instances complete (or are manually cancelled), deprecate linear engine
2. Hide old `/api/sequences/*` endpoints (keep functional for API consumers with deprecation warnings)
3. Remove linear engine code after grace period

---

## 14. Admin Notifications

### Error Alerts
- Instance enters `error` status → in-app notification to org admins
- Flow error rate > 10% over 1 hour → alert notification
- Touchpoint fails after all retries → notification with error details

### Delivery
- In-app notification bell (existing pattern if available)
- Optional email alerts (org-level setting)
- Future: WhatsApp alert to admin (using the same messaging infrastructure)

### Dashboard
- "Flow Health" widget showing: active flows, total active instances, error count, error rate
- Quick link to errored instances for debugging

---

## 15. Export / Import

- Export flow as JSON (FlowVersion with all nodes, edges, configs)
- Import JSON to create new flow (or new version of existing)
- Maintains parity with existing sequence export/import
- Portable between orgs (strips org-specific IDs on export)

---

## 16. Phase 2: Document Generation Node (Future)

Deferred to Phase 2. Design notes for future reference:

```json
{
  "node_type": "generate_document",
  "config": {
    "template_type": "html",
    "template_content": "<html>...{{contact_name}}...{{ai_proposal}}...</html>",
    "ai_fields": {
      "ai_proposal": {
        "prompt": "Generate a coaching proposal for {{contact_name}}...",
        "model": "claude-sonnet-4-6"
      }
    },
    "output_format": "pdf",
    "send_via": "whatsapp_template",
    "template_name": "document_share",
    "template_param_key": "document_url"
  }
}
```

Approach: HTML template → AI fills dynamic fields → Puppeteer/wkhtmltopdf renders PDF → upload to storage → send download URL via WhatsApp.
