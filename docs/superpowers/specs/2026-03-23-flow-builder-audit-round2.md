# Flow Builder Design Audit — Round 2

**Date:** 2026-03-23
**Auditor:** Claude (automated)
**Scope:** Frontend reuse, React Flow feasibility, remaining product gaps

---

## 1. Frontend Reuse Assessment

### Reusable (with adaptation)
| Component | Reuse strategy |
|---|---|
| `ImportExportDialog` | Adapt JSON schema from `{template, steps[]}` to `{flow, nodes[], edges[]}`. ~60% reuse. |
| `PromptTestPanel` | Direct reuse — AI prompt testing is node-agnostic. |
| `SequencesTab` (leads) | Rename to "Flows" tab, swap instance list for flow-enrollment list. ~50% reuse. |
| `sequences-api.ts` types | `SequenceInstance`, `SequenceTouchpoint`, `TemplateVariable` are structurally reusable. `SequenceStep` is **not** — replaced by `FlowNode`. |
| Analytics page (`analytics/page.tsx`) | Recharts setup, metric cards, date filters all reusable. Swap step-funnel for node-path analytics. ~70% reuse. |
| Monitor page (`monitor/page.tsx`) | Instance status table, filters, real-time polling — ~80% reuse. |

### Full Rewrite Required
| Component | Reason |
|---|---|
| `StepCard` | Deeply coupled to linear `step_order`, `channel`, `timing_type`. Flow nodes need type-specific config panels (call node vs condition node vs delay node). |
| `TouchpointTimeline` | Linear timeline rendering. Replace with React Flow canvas. |
| `[id]/page.tsx` (sequence editor) | The entire editor is a vertical step list with drag-reorder. Replaced by canvas. |

### New Components Needed
- `FlowCanvas` (React Flow wrapper)
- Per-node-type config panels: `CallNodePanel`, `WhatsAppNodePanel`, `ConditionNodePanel`, `DelayNodePanel`, `WaitEventNodePanel`, `GoalMetNodePanel`, `AIGenerateNodePanel`
- `NodePalette` sidebar (drag-to-add)
- `FlowValidationPanel` (error list)
- `SimulationOverlay` (dry-run path highlighting)
- `FlowVersionHistory` panel

## 2. New Types Needed (`sequences-api.ts`)

```ts
// Replace SequenceStep with:
interface FlowNode {
  id: string;
  flow_id: string;
  type: 'voice_call' | 'whatsapp_template' | 'whatsapp_session' | 'ai_generate'
      | 'condition' | 'delay' | 'wait_event' | 'goal_met' | 'end';
  position: { x: number; y: number };
  config: Record<string, any>;  // type-specific
  version: number;
}

interface FlowEdge {
  id: string;
  flow_id: string;
  source_node_id: string;
  target_node_id: string;
  source_handle: string;  // e.g. "picked_up", "no_answer", "default"
  label?: string;
  version: number;
}

interface Flow {
  id: string;
  name: string;
  status: 'draft' | 'published';
  current_version: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  created_at: string;
  updated_at: string;
}

interface FlowEnrollment {
  id: string;
  flow_id: string;
  flow_version: number;
  lead_id: string;
  current_node_id: string;
  status: 'active' | 'paused' | 'completed' | 'errored';
  started_at: string;
  error_info?: { node_id: string; error_type: string; message: string };
}
```

## 3. Lead Detail Page — Flow History Tab

Current structure (`leads/[leadId]/page.tsx`): Tabs = Overview | Call History | Sequences.

**Change:** Rename "Sequences" tab to "Flows". The existing `SequencesTab` shows a list of `SequenceInstance` entries. Replace with `FlowEnrollment` list, each linking to the canvas with that lead's path highlighted. Add a mini journey timeline per enrollment (node visited -> outcome -> next node).

## 4. React Flow + Next.js Feasibility

| Concern | Status |
|---|---|
| **SSR compatibility** | React Flow is client-only. Next.js 16 with `"use client"` directive handles this fine. The existing codebase already uses `"use client"` on all interactive pages. No issue. |
| **Package conflicts** | None. React 19 is supported by `@xyflow/react` v12+. No conflicting drag/canvas libraries in current deps. |
| **Bundle size** | `@xyflow/react` is ~45KB gzipped. Acceptable alongside existing framer-motion (~30KB). |
| **next.config.ts** | Current config is minimal (just API rewrites). No `transpilePackages` needed for React Flow. |

**Recommendation:** Install `@xyflow/react` (not the legacy `reactflow` package).

## 5. Remaining Product Gaps

### GAP 1: Parallel Branches (CRITICAL)
The design says "DAG" but never addresses fan-out/fan-in. Questions unanswered:
- Can a condition node have 3+ branches running simultaneously? (e.g., "picked_up" -> follow-up, AND separately "no_answer" -> retry)
- Those are exclusive branches (only one fires), which is fine. But can a non-condition node have multiple outgoing edges to trigger parallel paths?
- If parallel paths exist, what happens at convergence? Does the lead wait for all paths to complete (join), or does first-to-finish win?

**Recommendation:** v1 should be **exclusive branching only** (condition nodes pick ONE branch). State this explicitly. Add "parallel split" as a v2 node type if needed.

### GAP 2: Error Handling at Runtime (CRITICAL)
No error branch on action nodes. When WhatsApp send fails, AI generation fails, or provider is down:
- Does the lead get stuck on that node forever?
- Is there a retry policy per action node? (How many retries? Backoff?)
- Is there a global "on error" handler per flow?
- Does the system create an alert/notification?

**Recommendation:** Every action node needs a hidden "error" output handle. Default behavior: retry 3x with exponential backoff, then route to error handle. If no error edge connected, pause the enrollment and notify admin.

### GAP 3: Flow Cloning/Duplication (MODERATE)
Not mentioned anywhere. Users will want to:
- Duplicate a flow to iterate without touching the published version
- Use a published flow as a starting template for a new one

**Recommendation:** Add "Duplicate Flow" action on the flow list page. Clones nodes, edges, config into a new draft.

### GAP 4: Keyboard Shortcuts (MODERATE)
Only undo/redo mentioned. Canvas editors need:
- `Delete` / `Backspace` — delete selected node(s)/edge(s)
- `Cmd+C` / `Cmd+V` — copy/paste nodes (with offset)
- `Cmd+A` — select all
- `Cmd+D` — duplicate selected
- `Escape` — deselect all
- `Cmd+S` — save draft
- `Space+drag` — pan canvas (React Flow default)
- `Cmd+Plus/Minus` — zoom

**Recommendation:** React Flow provides most of these by default. Document which are enabled, add `Cmd+S` for save.

### GAP 5: Mobile/Tablet Responsiveness (LOW)
Canvas flow builders are inherently desktop experiences. The design doesn't state this.

**Recommendation:** Explicitly state "desktop-only for flow editing." On mobile, show read-only flow visualization (zoom/pan) and a "switch to desktop to edit" banner. The flow list page and analytics should remain responsive.

### GAP 6: Permissions/RBAC (MODERATE)
No mention of who can create/edit/publish/delete flows. Current codebase has no visible RBAC layer (all authed users seem equal).

**Recommendation:** For v1, all org members can edit drafts, but only admins can publish. Add `can_publish` permission. Deleting a flow with active enrollments should require admin.

### GAP 7: Export/Import for Flows (LOW)
Current sequences have `ImportExportDialog` for JSON export/import. The design doesn't mention whether flows support this.

**Recommendation:** Keep it. Export `{flow, nodes[], edges[]}` as JSON. Import creates a new draft. Useful for sharing flow templates between orgs.

### GAP 8: Error/Stuck Notifications (CRITICAL)
No mention of notifying users when:
- A lead is stuck on a node due to repeated failures
- A flow has a high error rate
- Rate limiting is causing significant queuing

**Recommendation:** Add a notification system: in-app notification bell + optional email/WhatsApp to admin when:
1. Any enrollment enters "errored" status
2. A flow's error rate exceeds 10% in a 1-hour window
3. Rate-limit queue depth exceeds 50 leads

### GAP 9: Compressed Delay in Live Test (LOW)
"Compressed delays" mentioned but no spec. What ratio? Is it configurable?

**Recommendation:** Default compression: delays under 1 hour -> 10 seconds, delays 1-24 hours -> 1 minute, delays 24+ hours -> 5 minutes. Show a banner "delays compressed for testing" with actual vs compressed time. Not configurable in v1.

### GAP 10: WhatsApp Session Node — 24hr Window Edge Case (MODERATE)
The design says "fallback to template if 24hr expired, or expired branch." But:
- How does the system know if the 24hr window is open? It needs to track the last inbound message timestamp per lead.
- What if the window expires BETWEEN the node being reached and the message being sent (race condition)?

**Recommendation:** Check window at send time, not at node entry. If expired at send time, follow the "expired" branch. Store `last_inbound_whatsapp_at` on the lead model.

### GAP 11: Goal Met Node Semantics (MODERATE)
"Goal Met" is described as "milestone, flow continues." But:
- What does "flow continues" mean exactly? Does the lead proceed to the next node?
- Can there be multiple Goal Met nodes in one flow? If yes, does reaching the first one count as "converted" in analytics?
- Is Goal Met just a marker, or does it also trigger an action (e.g., update lead status)?

**Recommendation:** Goal Met = a pass-through marker that (1) logs a conversion event, (2) optionally updates lead status, (3) continues to the next connected node. Multiple Goal Met nodes are allowed (representing sub-goals). Analytics should track each separately.

### GAP 12: Re-enrollment Rules (MODERATE)
Design says "manual re-enroll option" but:
- Can a lead be enrolled in the same flow twice simultaneously?
- If a lead completes a flow, can they be auto-re-enrolled on a trigger?
- What happens if a lead is in Flow A and gets enrolled in Flow B — do they run in parallel?

**Recommendation:** (1) No duplicate simultaneous enrollments in the same flow. (2) Re-enrollment after completion is manual only in v1. (3) Multiple different flows can run in parallel for the same lead, subject to rate limits.

---

## 6. Summary

| Priority | Gap | Risk |
|---|---|---|
| CRITICAL | Error handling / retry on action nodes | Leads silently stuck |
| CRITICAL | Error/stuck notifications | Admin unaware of failures |
| CRITICAL | Parallel branch semantics | Ambiguous DAG behavior |
| MODERATE | Flow cloning | UX friction |
| MODERATE | Permissions (publish/delete) | Accidental publish by non-admin |
| MODERATE | WhatsApp 24hr window race | Message delivery failure |
| MODERATE | Goal Met semantics | Unclear analytics |
| MODERATE | Re-enrollment rules | Duplicate enrollment bugs |
| MODERATE | Keyboard shortcuts spec | Power user friction |
| LOW | Mobile responsiveness statement | User confusion |
| LOW | Export/Import for flows | Feature parity |
| LOW | Compressed delay ratio | Untestable live test |

**Estimated frontend effort:** ~60% new code, ~40% reusable from current sequence UI. The biggest new piece is the React Flow canvas + node config panels. Analytics, monitor, and lead integration are mostly adaptation.
