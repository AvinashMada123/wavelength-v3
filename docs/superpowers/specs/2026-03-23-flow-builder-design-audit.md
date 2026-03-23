# Sequence Flow Builder — Design Audit

**Date:** 2026-03-23
**Auditor:** Claude
**Scope:** UX/Product gaps, edge cases, migration risks, missing features
**Codebase reviewed:** Frontend sequences pages, StepCard, TouchpointTimeline, sequences-api.ts, monitor, analytics, leads SequencesTab, backend API routes

---

## 1. Product / UX Gaps

### 1.1 User Confusion Risk — HIGH

**Current state:** The existing editor is a simple vertical list of StepCards with up/down reorder buttons (`sequence-editor-page`). Users add steps linearly via an "Add Step" button. Channel selection is a dropdown (whatsapp_template, whatsapp_session, voice_call, sms). This is a form-based UI that Indian coaches already understand.

**Risk:** A React Flow canvas is a massive UX leap. Non-technical coaches will face:
- **Spatial disorientation** — where do I put the next node? What do the lines mean?
- **Connection confusion** — dragging handles between nodes is a learned interaction pattern
- **Condition logic** — branching on call outcomes requires understanding IF/ELSE logic visually
- **Canvas navigation** — zoom, pan, minimap are alien to form-based users

**Recommended guardrails:**
- **Guided mode (v1 default):** Auto-layout nodes vertically. Users click "Add next step" on a node, system places it automatically. Only expose free-form canvas as "Advanced mode."
- **Connection validation:** Prevent invalid connections (e.g., two edges into a Delay node's input). Show red highlight + tooltip explaining why.
- **Snap-to-grid:** Prevent messy layouts.
- **Minimap + breadcrumb:** Always visible so users don't get lost in large flows.
- **Max visible complexity:** Collapse sub-branches by default when flow exceeds ~15 nodes.

### 1.2 Onboarding — CRITICAL GAP

**Nothing in the design addresses first-time experience.** The current editor has an empty state ("No steps yet — Add your first step") in `sequence-editor-page`. A flow builder needs much more:

**Required:**
- **3-5 pre-built templates:** "Post-call follow-up", "No-answer retry", "Course launch drip", "Webinar reminder sequence", "Payment follow-up". Users start from templates, not blank canvas.
- **Interactive tutorial:** First visit triggers a 4-step guided tour (add node → connect → configure → publish). Use existing `sonner` toast pattern for non-intrusive hints.
- **Example flows:** Read-only demo flows users can clone.
- **"Simple mode" toggle:** For users who just want the old linear step list (renders as a straight-line flow internally).

### 1.3 Error States — INCOMPLETE

**Must validate before publish:**

| Error | Severity | UX Treatment |
|-------|----------|-------------|
| No End node | Warning (not error — flow can end implicitly when no next node) | Yellow banner: "Flow has no explicit End node. Leads will stop after the last action." |
| Disconnected nodes | Error | Highlight orphaned nodes in red, prevent publish |
| Infinite loops | Error | Detect cycles in DAG, highlight loop edges in red |
| Condition with missing branch | Warning | "What happens if none of the conditions match?" — require default/else branch |
| Empty action node | Error | Node configured but no template/bot selected |
| Wait for Event with no timeout | Error | Design says "mandatory timeout, default 24hrs" — enforce this |
| Dead-end condition branch | Warning | Branch leads nowhere (no End node, no next step) |

**Missing from design:** What happens at runtime when a node fails? Current touchpoint model has `error_message` and `retry_count`/`max_retries`. The flow builder needs a **visual error state on canvas** (red badge on node) + **manual retry button** (already exists in TouchpointTimeline component).

### 1.4 Flow Validation — Specifics

Before publish, run these checks:
1. **Graph connectivity:** All nodes reachable from trigger/start node (BFS/DFS)
2. **Cycle detection:** No loops unless explicitly allowed (e.g., retry loops must have exit conditions)
3. **Resource completeness:** Every voice_call node has a bot_id assigned (current StepCard already validates this). Every whatsapp_template node has template + params.
4. **Timing sanity:** Delay of 0 seconds is suspicious. Delay > 30 days is suspicious. Warn, don't block.
5. **WhatsApp 24hr window:** If a whatsapp_session node follows a delay > 24hrs, warn that the session window will likely be expired.
6. **Business hours conflicts:** A node set to "business hours only" followed by an "immediate" node — the immediate node will fire during business hours anyway (clarify behavior).

### 1.5 Mobile Responsiveness — DECISION NEEDED

**Current app is responsive** — shadcn/ui components, Tailwind CSS, sidebar collapses. The monitor page uses responsive tables.

**Canvas UIs are fundamentally desktop-only.** React Flow does not work well on mobile. Options:
- **(A) Desktop-only editor, read-only mobile view** — show flow as a simplified list on mobile. This is the pragmatic choice.
- **(B) Desktop-only entirely** — redirect mobile users to a "use desktop" message. Bad for Indian market where mobile-first is common.
- **(C) Hybrid** — simple mode (linear list) on mobile, canvas on desktop.

**Recommendation:** Option A. The monitor/analytics pages should remain mobile-friendly (they already are). Only the editor needs desktop.

---

## 2. Edge Cases

### 2.1 Concurrent Execution — Lead Hits Condition While Call Ringing

**Current model:** `SequenceTouchpoint` has statuses (pending, sent, completed, failed). `SequenceInstance` tracks `current_step`.

**Problem:** If a Condition node checks "call outcome = picked_up" but the call is still `status=pending` (ringing), the condition has no data to evaluate.

**Solution:** The engine must **block at Condition nodes until all upstream dependencies are resolved.** Specifically:
- If Condition references call outcome, wait until the call touchpoint reaches a terminal status (completed/failed).
- Add a `waiting_for_dependency` status to touchpoints.
- Timeout: if the call never resolves (Plivo webhook lost), auto-fail after configurable timeout (default: 30 min).

### 2.2 WhatsApp 24hr Window Expiry

**Current model:** Touchpoint has `session_window_expires_at` field — already tracked!

**Problem:** Flow reaches a WhatsApp Session node, but `session_window_expires_at` is in the past.

**Solution:**
- At execution time, check window. If expired, **auto-fallback to WhatsApp Template** (requires pre-configured fallback template on the node).
- Or mark touchpoint as `failed` with `error_message: "Session window expired"` and let the flow's condition handle it.
- **Design gap:** The proposed design doesn't mention this fallback behavior. It must be explicit — coaches won't understand why a message "silently failed."

### 2.3 Lead at Multiple Nodes Simultaneously (Parallel Branches)

**Current model:** `SequenceInstance` has a single `current_step` integer. This fundamentally cannot support parallel branches.

**Problem:** If a Condition node branches into two paths (e.g., "interested" → call, "not interested" → WhatsApp), only one executes. But what about a **fork node** (both paths execute)?

**Decision needed:**
- **(A) No parallel execution in v1.** Condition = exclusive branch (only one path). This matches the current `current_step` model. Simple, safe.
- **(B) Support parallel branches.** Requires replacing `current_step` with a `current_positions: list[node_id]` field. Complex, error-prone.

**Recommendation:** Option A for v1. The design already implies exclusive branching (Condition node). Just make it explicit: **no fork/join pattern in v1.**

### 2.4 Flow Size Limits

**Problem:** Someone creates a 500-node flow. React Flow performance degrades > 100 nodes. Backend graph traversal could be slow.

**Guardrails:**
- **Soft limit:** Warning at 50 nodes ("This flow is getting complex. Consider splitting into multiple flows.")
- **Hard limit:** 200 nodes max. Beyond this, the UX is unusable anyway.
- **Backend:** Store flow as adjacency list in JSONB. Query complexity is O(V+E) which is fine up to thousands.
- **Frontend:** React Flow handles 200 nodes fine with virtualization. Above that, use `onlyRenderVisibleElements`.

### 2.5 Undo/Redo — NOT MENTIONED

**Critical omission.** Canvas editors without undo/redo are unusable. Users will accidentally delete nodes/edges.

**Implementation:**
- Use React Flow's built-in undo/redo support or implement with a command stack pattern.
- Store last 50 operations.
- Keyboard shortcuts: Cmd+Z / Cmd+Shift+Z (current app already has keyboard shortcut infrastructure — see `command-palette.tsx` and `keyboard-shortcuts-help.tsx`).
- **Also needed:** Delete confirmation dialog for nodes that have active leads.

---

## 3. Migration & Backwards Compatibility

### 3.1 Existing Linear Sequences → Flow Migration

**Current data model:**
- `SequenceTemplate` — has `trigger_type`, `is_active`, `steps` (ordered list)
- `SequenceStep` — has `step_order`, `channel`, `timing_type`, `timing_value`, `content_type`, `template_body`, `ai_prompt`, `bot_id`, `max_retries`

**Migration path:**
1. **Auto-convert:** Each linear sequence becomes a flow: Start → Step1 → Step2 → ... → End. Delays become edges with timing metadata (or inline Delay nodes).
2. **One-time migration script:** Run on deploy. Create `flow_definition` JSONB column on `SequenceTemplate` containing nodes + edges.
3. **Dual-read period:** Engine reads `flow_definition` if present, falls back to `steps` list if not. Deprecate `steps` after 30 days.
4. **UI:** Old editor disappears. All templates appear in new flow builder (auto-converted ones show as straight vertical flows).

**Risk:** If auto-conversion has bugs, active sequences break. **Mitigation:** Run conversion in preview mode first, let users verify before activating.

### 3.2 Leads Mid-Sequence During Migration

**Current model:** `SequenceInstance` tracks `current_step` (integer step_order). Touchpoints reference step snapshots.

**Migration plan:**
- `current_step` integer maps to a `current_node_id` in the new flow.
- Migration script creates a mapping: `step_order → node_id` for each auto-converted template.
- Active instances continue from their mapped position.
- **Edge case:** If a lead is at step 3 of 5, and the user edits the flow (adds a branch after step 2), the lead should continue at the node that was formerly step 3, not get lost.

**The design says "publish migrates ALL leads to new version."** This is dangerous. If a user restructures the flow completely, leads mid-sequence have no valid position in the new graph.

**Recommendation:** On publish, if there are active leads:
1. Show a warning: "X leads are currently active in this flow."
2. Options: (a) Migrate leads to best-match positions, (b) Complete active leads on old version, start new enrollments on new version, (c) Cancel all active instances.
3. Option (b) is safest — run two versions simultaneously until old drains.

### 3.3 API Compatibility

**Current API surface** (from `sequences-api.ts`):
- `fetchTemplates`, `fetchTemplate`, `createTemplate`, `updateTemplate`, `deleteTemplate`
- `addStep`, `updateStep`, `deleteStep`, `reorderSteps`
- `exportTemplate`, `importTemplate`
- Instance management: `fetchInstances`, `pauseInstance`, `resumeInstance`, `cancelInstance`, `advanceInstance`
- Touchpoints: `fetchTouchpoints`, `retryTouchpoint`
- Analytics: `fetchAnalyticsOverview`, `fetchAnalyticsFunnel`, `fetchAnalyticsFailures`

**Breaking changes:**
- `addStep`, `updateStep`, `deleteStep`, `reorderSteps` — these step CRUD endpoints become node/edge CRUD endpoints. The concept of `step_order` disappears.
- `advanceInstance` — currently advances to next step_order. In flow model, must specify which edge/path to take, or auto-advance based on conditions.
- `exportTemplate` / `importTemplate` — format changes (includes nodes + edges instead of step list).

**Recommendation:**
- Keep old step endpoints working for 1 release cycle (read-only, deprecated).
- New endpoints: `PUT /templates/{id}/flow` (save entire flow graph), `GET /templates/{id}/flow`.
- Instance/touchpoint APIs stay the same — they don't depend on step ordering.
- Export format v2 with backwards-compatible import (detect format version).

---

## 4. Missing Features

### 4.1 Flow Templates/Presets — CRITICAL for adoption

The current app has `ImportExportDialog` for JSON import/export. This is power-user territory.

**Needed:**
- **Template gallery** on the "Create Sequence" page. Show 5-8 pre-built flows with preview thumbnails.
- **Categories:** Follow-up, Nurture, Reactivation, Event-based.
- **Customizable:** User picks template, it populates the canvas, they edit to fit their needs.
- **Community templates (v2):** Share flows between orgs.

### 4.2 Copy/Duplicate Flow

**Currently exists for templates** — the list page (`sequences/page.tsx`) likely has duplicate. But duplicating a flow graph (deep-clone all nodes + edges + generate new IDs) needs explicit support.

Also needed: **Copy individual nodes** (Cmd+C/Cmd+V on canvas) and **copy node groups** (select multiple, duplicate).

### 4.3 Collaboration / Concurrent Editing

**Not needed for v1.** Target users are small teams (1-3 people). But add **basic locking:**
- When User A opens a flow editor, show a banner to User B: "User A is currently editing this flow."
- Don't block, just warn. Last-save-wins is acceptable for v1.

### 4.4 Audit Log

**Currently missing entirely from the app.** For flows, track:
- Flow published/unpublished (who, when)
- Flow structure changed (diff of nodes/edges)
- Lead enrolled/removed manually (who, when)

**Implementation:** Add `audit_log` table. Low priority for v1 but valuable for debugging when coaches say "I didn't change anything and it broke."

### 4.5 Rate Limiting — CRITICAL SAFETY NET

**Scenario:** A flow with a tight loop or a condition that immediately re-triggers can flood a lead with messages.

**Guardrails:**
- **Per-lead rate limit:** Max 5 messages/day across all flows (configurable at org level).
- **Per-flow rate limit:** Max 20 messages/day per lead per flow.
- **Burst protection:** If a lead would receive > 2 messages within 5 minutes, pause and alert.
- **The design mentions `max_active_per_lead`** — good. But it prevents enrollment, not message flooding within a single flow.

### 4.6 Additional Missing Features

**Not in the design but needed:**

1. **Flow versioning with diff view:** When a user publishes, show what changed (added/removed/modified nodes) before confirming. The current app has no version history.

2. **Webhook/API trigger node:** The design mentions keeping existing triggers but "architect for extensibility." Be concrete: a Webhook trigger node that fires the flow when an external event hits an endpoint. Indian coaches use GHL (GoHighLevel) and need this.

3. **A/B testing:** Split node that randomly assigns leads to different paths (e.g., 50% get WhatsApp, 50% get voice call). Very common in marketing automation.

4. **Lead variable interpolation in conditions:** The design mentions "branch on lead fields" but current `SequenceStep` has `variables` support (see editor page's variable management). Ensure flow conditions can reference these variables.

5. **Timezone handling:** Business hours per node implies timezone awareness. Current backend likely uses UTC. Indian coaches serve students across IST but may have international clients. Store timezone on org, allow override per flow.

6. **Notification on flow errors:** When a touchpoint fails or a flow gets stuck, notify the coach via WhatsApp/email. Currently, they'd only notice by checking the monitor page.

---

## 5. Architecture Recommendations

### 5.1 Data Model

```
SequenceTemplate (existing, extended)
  + flow_definition: JSONB {
      nodes: [{id, type, position, data: {channel, config, ...}}],
      edges: [{id, source, target, sourceHandle, data: {condition, ...}}],
      viewport: {x, y, zoom}
    }
  + flow_version: integer
  + is_draft: boolean (currently no draft concept)

FlowExecution (new, replaces current_step tracking)
  instance_id → SequenceInstance
  current_node_ids: UUID[]  -- for future parallel support
  execution_history: JSONB [{node_id, entered_at, exited_at, outcome}]
```

### 5.2 Frontend Architecture

- **New dependency:** `@xyflow/react` (React Flow v12). Not currently in package.json.
- **New pages:** `/sequences/[id]/flow` (canvas editor), keep `/sequences/[id]` as redirect or legacy.
- **State management:** React Flow has its own store. Sync with React Query for persistence. Use `useNodesState` + `useEdgesState` hooks.
- **Custom nodes:** One React component per node type (ActionNode, ConditionNode, DelayNode, EndNode). Use shadcn Card as base — consistent with existing UI.
- **Node config panel:** Slide-out Sheet (already using shadcn Sheet for sidebar). Click node → Sheet opens with config form. Reuse existing StepCard field patterns (channel select, timing config, template body textarea, bot selector).

### 5.3 Performance Considerations

- **Canvas rendering:** React Flow virtualizes nodes by default. Enable `onlyRenderVisibleElements` for flows > 50 nodes.
- **Auto-save:** Debounce at 2 seconds. Save entire `flow_definition` JSONB. Don't do per-node saves (too many API calls during drag operations).
- **Flow execution engine:** Backend should evaluate the graph lazily (only compute next node when current node completes). Don't pre-compute the entire path.

---

## 6. Priority Matrix

| Item | Impact | Effort | Priority |
|------|--------|--------|----------|
| Guided/auto-layout mode | HIGH | Medium | P0 — without this, coaches won't adopt |
| Flow templates | HIGH | Low | P0 — critical for onboarding |
| Flow validation before publish | HIGH | Medium | P0 — prevents broken flows |
| Undo/redo | HIGH | Low | P0 — table stakes for canvas UX |
| WhatsApp window expiry handling | HIGH | Low | P0 — silent failures are unacceptable |
| Rate limiting / flood protection | HIGH | Medium | P0 — safety net |
| Migration script (linear → flow) | HIGH | Medium | P0 — required for launch |
| Active lead version handling | HIGH | High | P0 — data safety |
| Concurrent execution blocking | Medium | Medium | P1 |
| Mobile read-only view | Medium | Medium | P1 |
| Node copy/paste | Medium | Low | P1 |
| Flow size limits | Low | Low | P1 |
| Audit log | Medium | Medium | P2 |
| A/B split testing | Medium | High | P2 |
| Collaboration locking | Low | Low | P2 |
| Flow versioning with diff | Medium | High | P2 |

---

## 7. Summary of Critical Findings

1. **The biggest risk is UX complexity for non-technical coaches.** A guided/auto-layout mode that defaults to linear flows (with branching as opt-in) is essential. Without it, adoption will be poor.

2. **"Publish migrates ALL leads" is dangerous.** Active leads need a safe migration path — either complete-on-old-version or explicit position mapping with user confirmation.

3. **No undo/redo, no templates, no onboarding** — these aren't nice-to-haves, they're launch blockers for the target audience.

4. **WhatsApp 24hr window and rate limiting** are runtime safety issues that will cause real damage (failed messages, lead harassment) if not addressed before launch.

5. **The current data model (`current_step` integer) cannot represent flow positions.** This is a fundamental schema change requiring careful migration.

6. **React Flow is not in package.json yet** — `@xyflow/react` needs to be added. No other canvas library is present.
