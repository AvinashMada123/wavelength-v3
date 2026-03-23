# Flow Builder Plan 4: Frontend — Flow Canvas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the flow canvas UI — the visual drag-and-drop flow builder using React Flow. This includes the flow list page, canvas page with node palette, custom node components, properties panel, undo/redo, auto-layout, draft/publish UI, and flow templates.

**Architecture:** All new files live under `frontend/src/`. The canvas page is a `"use client"` component using `@xyflow/react` for the node graph. State management uses React hooks (useState/useCallback) matching existing patterns. The API client (`flows-api.ts`) follows the same `apiFetch` pattern as `sequences-api.ts`. Custom nodes render inside React Flow's node system. Undo/redo uses a command-pattern history stack held in a React ref.

**Tech Stack:** Next.js 16, React 19, `@xyflow/react`, shadcn/ui, Tailwind, Radix, lucide-react, dagre (for auto-layout), sonner (toasts)

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §9, §3, §4, §6, §7, §12

**Dependencies:** Plan 2 (database tables) and Plan 3 (API endpoints) must be complete — this plan calls those endpoints.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Install | `package.json` | Add `@xyflow/react` and `@dagrejs/dagre` dependencies |
| Create | `frontend/src/lib/flows-api.ts` | TypeScript types + API client for all flow endpoints |
| Create | `frontend/src/lib/flow-types.ts` | Shared flow type definitions (node types, edge types, configs) |
| Create | `frontend/src/lib/flow-validation.ts` | Client-side flow validation (mirrors server rules) |
| Create | `frontend/src/lib/flow-layout.ts` | Dagre auto-layout algorithm integration |
| Create | `frontend/src/lib/flow-templates.ts` | Predefined flow templates (blank, post-call follow-up, etc.) |
| Create | `frontend/src/hooks/use-flow-history.ts` | Undo/redo command-pattern hook |
| Modify | `frontend/src/app/(app)/sequences/page.tsx` | Adapt to show both legacy templates and new flows |
| Create | `frontend/src/app/(app)/sequences/[id]/flow/page.tsx` | Flow canvas page (main builder) |
| Create | `frontend/src/components/flow/NodePalette.tsx` | Left sidebar — draggable node types by category |
| Create | `frontend/src/components/flow/PropertiesPanel.tsx` | Right sidebar — selected node configuration |
| Create | `frontend/src/components/flow/CanvasToolbar.tsx` | Top toolbar — undo/redo, zoom, validate, publish |
| Create | `frontend/src/components/flow/nodes/VoiceCallNode.tsx` | Custom React Flow node for voice calls |
| Create | `frontend/src/components/flow/nodes/WhatsAppTemplateNode.tsx` | Custom node for WhatsApp template messages |
| Create | `frontend/src/components/flow/nodes/WhatsAppSessionNode.tsx` | Custom node for WhatsApp session messages |
| Create | `frontend/src/components/flow/nodes/AIGenerateNode.tsx` | Custom node for AI generate + send |
| Create | `frontend/src/components/flow/nodes/ConditionNode.tsx` | Custom node for condition branching |
| Create | `frontend/src/components/flow/nodes/DelayWaitNode.tsx` | Custom node for delay/wait |
| Create | `frontend/src/components/flow/nodes/WaitForEventNode.tsx` | Custom node for event waiting |
| Create | `frontend/src/components/flow/nodes/GoalMetNode.tsx` | Custom node for goal tracking |
| Create | `frontend/src/components/flow/nodes/EndNode.tsx` | Custom node for flow termination |
| Create | `frontend/src/components/flow/nodes/BaseNode.tsx` | Shared base wrapper for all custom nodes |
| Create | `frontend/src/components/flow/FlowCanvas.tsx` | Main canvas container composing all parts |
| Create | `frontend/src/components/flow/TemplatePicker.tsx` | Template picker dialog for new flow creation |
| Create | `frontend/src/components/flow/ValidationPanel.tsx` | Validation results display (errors + warnings) |

---

## Task 1: Install Dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install `@xyflow/react` and `@dagrejs/dagre`**

Run:
```bash
cd frontend && npm install @xyflow/react @dagrejs/dagre
```

- [ ] **Step 2: Install dagre type definitions**

Run:
```bash
cd frontend && npm install -D @types/dagre
```

Note: `@dagrejs/dagre` ships its own types via `@types/dagre`. If types are already bundled, skip the second install.

- [ ] **Step 3: Verify installation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No new type errors introduced.

---

## Task 2: TypeScript Types + API Client

**Files:**
- Create: `frontend/src/lib/flow-types.ts`
- Create: `frontend/src/lib/flows-api.ts`

- [ ] **Step 1: Create shared flow type definitions**

```typescript
// frontend/src/lib/flow-types.ts

// ---------------------------------------------------------------------------
// Node type enum — matches backend FlowNode.node_type
// ---------------------------------------------------------------------------
export const NODE_TYPES = [
  "voice_call",
  "whatsapp_template",
  "whatsapp_session",
  "ai_generate_send",
  "condition",
  "delay_wait",
  "wait_for_event",
  "goal_met",
  "end",
] as const;

export type FlowNodeType = (typeof NODE_TYPES)[number];

// ---------------------------------------------------------------------------
// Node configuration schemas (per §4 of spec)
// ---------------------------------------------------------------------------
export interface SendWindow {
  enabled: boolean;
  start?: string;
  end?: string;
  resume_at?: string;
  days: string[];
  timezone: string;
}

export interface VoiceCallConfig {
  bot_id: string;
  quick_retry: {
    enabled: boolean;
    max_attempts: number;
    interval_hours: number;
  };
  send_window: SendWindow;
}

export interface WhatsAppTemplateConfig {
  template_name: string;
  template_params: Record<string, string>;
  ai_param_generation: {
    enabled: boolean;
    param_key: string;
    prompt: string;
  };
  send_window: SendWindow;
}

export interface WhatsAppSessionConfig {
  message: string | null;
  ai_generation: {
    enabled: boolean;
    prompt: string;
    model: string;
  };
  on_window_expired: "fallback_template" | "expired_branch";
  fallback_template_name: string;
  expects_reply: boolean;
  reply_handler: {
    action: "ai_respond" | "capture_field";
    ai_prompt: string;
    capture_field_name: string;
  };
  send_window: SendWindow;
}

export interface AIGenerateConfig {
  mode: "fill_template_vars" | "full_message";
  prompt: string;
  model: string;
  send_via: "whatsapp_session" | "whatsapp_template";
  template_name: string;
  template_param_key: string;
  send_window: SendWindow;
}

export interface ConditionRule {
  field: string;
  operator: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "regex";
  value: string | number;
}

export interface ConditionBranch {
  label: string;
  rules: ConditionRule[];
}

export interface ConditionConfig {
  conditions: ConditionBranch[];
  default_label: string;
}

export interface DelayWaitConfig {
  duration_value: number;
  duration_unit: "hours" | "minutes" | "days";
  send_window: SendWindow;
}

export interface WaitForEventConfig {
  event_type: "reply_received" | "call_completed";
  timeout_hours: number;
  timeout_label: string;
}

export interface GoalMetConfig {
  goal_name: string;
  goal_description: string;
}

export interface EndConfig {
  end_reason: "completed" | "disqualified" | "unresponsive";
}

export type NodeConfig =
  | VoiceCallConfig
  | WhatsAppTemplateConfig
  | WhatsAppSessionConfig
  | AIGenerateConfig
  | ConditionConfig
  | DelayWaitConfig
  | WaitForEventConfig
  | GoalMetConfig
  | EndConfig;

// ---------------------------------------------------------------------------
// Outgoing edge labels per node type
// ---------------------------------------------------------------------------
export const NODE_EDGE_LABELS: Record<FlowNodeType, string[]> = {
  voice_call: ["picked_up", "no_answer", "busy", "timeout", "failed", "voicemail"],
  whatsapp_template: ["sent", "failed"],
  whatsapp_session: ["sent", "replied", "expired", "failed"],
  ai_generate_send: ["sent", "failed"],
  condition: [], // dynamic — derived from config.conditions[].label + default_label
  delay_wait: ["completed"],
  wait_for_event: [], // dynamic — event_type label + timeout_label
  goal_met: ["continue"],
  end: [],
};

// ---------------------------------------------------------------------------
// API response types — matches backend models
// ---------------------------------------------------------------------------
export interface FlowDefinition {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  trigger_type: "post_call" | "manual" | "campaign_complete";
  trigger_conditions: Record<string, any>;
  max_active_per_lead: number;
  variables: Array<{ key: string; default_value: string; description: string }>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Included when fetching single flow
  draft_version?: FlowVersion;
  published_version?: FlowVersion;
  active_instance_count?: number;
}

export interface FlowVersion {
  id: string;
  flow_id: string;
  version_number: number;
  status: "draft" | "published" | "archived";
  is_locked: boolean;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  nodes: FlowNodeData[];
  edges: FlowEdgeData[];
}

export interface FlowNodeData {
  id: string;
  version_id: string;
  node_type: FlowNodeType;
  name: string;
  position_x: number;
  position_y: number;
  config: Record<string, any>;
  created_at: string;
}

export interface FlowEdgeData {
  id: string;
  version_id: string;
  source_node_id: string;
  target_node_id: string;
  condition_label: string;
  sort_order: number;
}

// ---------------------------------------------------------------------------
// Validation types
// ---------------------------------------------------------------------------
export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface ValidationIssue {
  node_id?: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Simulation types
// ---------------------------------------------------------------------------
export interface SimulationRequest {
  mock_lead: Record<string, any>;
  outcomes: Record<string, string>; // node_id → outcome label
}

export interface SimulationStep {
  node_id: string;
  node_type: FlowNodeType;
  action_preview: string;
  outcome: string;
}

export interface SimulationResult {
  path: SimulationStep[];
  goals_hit: string[];
  end_reason: string;
}

// ---------------------------------------------------------------------------
// Display metadata for node palette
// ---------------------------------------------------------------------------
export interface NodeTypeInfo {
  type: FlowNodeType;
  label: string;
  description: string;
  icon: string; // lucide icon name
  category: "action" | "control" | "terminal";
  color: string; // tailwind color class for the node border/accent
}

export const NODE_TYPE_REGISTRY: NodeTypeInfo[] = [
  { type: "voice_call", label: "Voice Call", description: "Make an AI voice call", icon: "Phone", category: "action", color: "border-blue-500" },
  { type: "whatsapp_template", label: "WhatsApp Template", description: "Send a pre-approved template", icon: "MessageSquare", category: "action", color: "border-green-500" },
  { type: "whatsapp_session", label: "WhatsApp Session", description: "Send a session message", icon: "MessageCircle", category: "action", color: "border-green-400" },
  { type: "ai_generate_send", label: "AI Generate + Send", description: "Generate and send AI content", icon: "Sparkles", category: "action", color: "border-purple-500" },
  { type: "condition", label: "Condition", description: "Branch based on data", icon: "GitBranch", category: "control", color: "border-amber-500" },
  { type: "delay_wait", label: "Delay / Wait", description: "Wait before continuing", icon: "Clock", category: "control", color: "border-slate-400" },
  { type: "wait_for_event", label: "Wait for Event", description: "Wait for an external event", icon: "Bell", category: "control", color: "border-slate-500" },
  { type: "goal_met", label: "Goal Met", description: "Record a goal achievement", icon: "Target", category: "terminal", color: "border-emerald-500" },
  { type: "end", label: "End", description: "Terminate the flow", icon: "CircleStop", category: "terminal", color: "border-red-500" },
];

// ---------------------------------------------------------------------------
// Default configs for new nodes
// ---------------------------------------------------------------------------
export function getDefaultConfig(nodeType: FlowNodeType): Record<string, any> {
  switch (nodeType) {
    case "voice_call":
      return {
        bot_id: "",
        quick_retry: { enabled: false, max_attempts: 3, interval_hours: 1 },
        send_window: { enabled: true, start: "09:00", end: "19:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"], timezone: "Asia/Kolkata" },
      };
    case "whatsapp_template":
      return {
        template_name: "",
        template_params: {},
        ai_param_generation: { enabled: false, param_key: "", prompt: "" },
        send_window: { enabled: true, start: "09:00", end: "19:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"], timezone: "Asia/Kolkata" },
      };
    case "whatsapp_session":
      return {
        message: "",
        ai_generation: { enabled: false, prompt: "", model: "gemini-2.5-flash" },
        on_window_expired: "fallback_template",
        fallback_template_name: "",
        expects_reply: false,
        reply_handler: { action: "ai_respond", ai_prompt: "", capture_field_name: "" },
        send_window: { enabled: true, start: "09:00", end: "19:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"], timezone: "Asia/Kolkata" },
      };
    case "ai_generate_send":
      return {
        mode: "full_message",
        prompt: "",
        model: "gemini-2.5-flash",
        send_via: "whatsapp_session",
        template_name: "",
        template_param_key: "",
        send_window: { enabled: true, start: "09:00", end: "19:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"], timezone: "Asia/Kolkata" },
      };
    case "condition":
      return { conditions: [], default_label: "other" };
    case "delay_wait":
      return {
        duration_value: 1,
        duration_unit: "hours",
        send_window: { enabled: false, resume_at: "09:00", days: ["mon", "tue", "wed", "thu", "fri"], timezone: "Asia/Kolkata" },
      };
    case "wait_for_event":
      return { event_type: "reply_received", timeout_hours: 24, timeout_label: "timed_out" };
    case "goal_met":
      return { goal_name: "", goal_description: "" };
    case "end":
      return { end_reason: "completed" };
  }
}
```

- [ ] **Step 2: Create the API client**

```typescript
// frontend/src/lib/flows-api.ts
import { apiFetch } from "./api";
import type {
  FlowDefinition,
  FlowVersion,
  FlowNodeData,
  FlowEdgeData,
  ValidationResult,
  SimulationRequest,
  SimulationResult,
} from "./flow-types";

// ---------------------------------------------------------------------------
// Flow CRUD
// ---------------------------------------------------------------------------
export async function fetchFlows(
  page = 1,
  limit = 50,
): Promise<{ flows: FlowDefinition[]; total: number }> {
  return apiFetch(`/api/flows?page=${page}&limit=${limit}`);
}

export async function fetchFlow(flowId: string): Promise<FlowDefinition> {
  return apiFetch(`/api/flows/${flowId}`);
}

export async function createFlow(data: {
  name: string;
  description?: string;
  trigger_type: string;
  template_id?: string; // if creating from template
}): Promise<FlowDefinition> {
  return apiFetch("/api/flows", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateFlow(
  flowId: string,
  data: Partial<Pick<FlowDefinition, "name" | "description" | "trigger_type" | "trigger_conditions" | "max_active_per_lead" | "variables" | "is_active">>,
): Promise<FlowDefinition> {
  return apiFetch(`/api/flows/${flowId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteFlow(flowId: string): Promise<void> {
  await apiFetch(`/api/flows/${flowId}`, { method: "DELETE" });
}

export async function cloneFlow(flowId: string): Promise<FlowDefinition> {
  return apiFetch(`/api/flows/${flowId}/clone`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Version operations
// ---------------------------------------------------------------------------
export async function fetchVersions(flowId: string): Promise<FlowVersion[]> {
  return apiFetch(`/api/flows/${flowId}/versions`);
}

export async function fetchVersion(
  flowId: string,
  versionId: string,
): Promise<FlowVersion> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}`);
}

export async function createDraftVersion(flowId: string): Promise<FlowVersion> {
  return apiFetch(`/api/flows/${flowId}/versions`, { method: "POST" });
}

/** Atomic graph save — replaces all nodes + edges in the draft version. */
export async function saveGraph(
  flowId: string,
  versionId: string,
  data: { nodes: FlowNodeData[]; edges: FlowEdgeData[] },
): Promise<FlowVersion> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------------------
// Node/Edge operations (granular, for real-time autosave)
// ---------------------------------------------------------------------------
export async function addNode(
  flowId: string,
  versionId: string,
  node: Omit<FlowNodeData, "id" | "version_id" | "created_at">,
): Promise<FlowNodeData> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/nodes`, {
    method: "POST",
    body: JSON.stringify(node),
  });
}

export async function updateNode(
  flowId: string,
  versionId: string,
  nodeId: string,
  data: Partial<FlowNodeData>,
): Promise<FlowNodeData> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/nodes/${nodeId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteNode(
  flowId: string,
  versionId: string,
  nodeId: string,
): Promise<void> {
  await apiFetch(`/api/flows/${flowId}/versions/${versionId}/nodes/${nodeId}`, {
    method: "DELETE",
  });
}

export async function addEdge(
  flowId: string,
  versionId: string,
  edge: Omit<FlowEdgeData, "id" | "version_id">,
): Promise<FlowEdgeData> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/edges`, {
    method: "POST",
    body: JSON.stringify(edge),
  });
}

export async function deleteEdge(
  flowId: string,
  versionId: string,
  edgeId: string,
): Promise<void> {
  await apiFetch(`/api/flows/${flowId}/versions/${versionId}/edges/${edgeId}`, {
    method: "DELETE",
  });
}

export async function updateLayout(
  flowId: string,
  versionId: string,
  positions: Array<{ node_id: string; position_x: number; position_y: number }>,
): Promise<void> {
  await apiFetch(`/api/flows/${flowId}/versions/${versionId}/layout`, {
    method: "PUT",
    body: JSON.stringify({ positions }),
  });
}

// ---------------------------------------------------------------------------
// Validation + Publish
// ---------------------------------------------------------------------------
export async function validateFlow(
  flowId: string,
  versionId: string,
): Promise<ValidationResult> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/validate`, {
    method: "POST",
  });
}

export async function publishVersion(
  flowId: string,
  versionId: string,
): Promise<FlowVersion> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/publish`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------
export async function simulateFlow(
  flowId: string,
  versionId: string,
  data: SimulationRequest,
): Promise<SimulationResult> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/simulate`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function startLiveTest(
  flowId: string,
  phoneNumber: string,
): Promise<{ instance_id: string }> {
  return apiFetch(`/api/flows/${flowId}/live-test`, {
    method: "POST",
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

---

## Task 3: Auto-Layout with Dagre

**Files:**
- Create: `frontend/src/lib/flow-layout.ts`

- [ ] **Step 1: Create dagre layout utility**

```typescript
// frontend/src/lib/flow-layout.ts
import dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";

const NODE_WIDTH = 240;
const NODE_HEIGHT = 80;

/**
 * Apply top-down dagre layout to a set of React Flow nodes and edges.
 * Returns new node array with updated positions — does not mutate input.
 */
export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB",
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 100,
    marginx: 40,
    marginy: 40,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 4: Undo/Redo Hook

**Files:**
- Create: `frontend/src/hooks/use-flow-history.ts`

- [ ] **Step 1: Create the undo/redo hook using command pattern**

```typescript
// frontend/src/hooks/use-flow-history.ts
"use client";

import { useCallback, useRef, useState } from "react";
import type { Node, Edge } from "@xyflow/react";

interface HistoryEntry {
  nodes: Node[];
  edges: Edge[];
  label: string; // human-readable description for debugging
}

const MAX_HISTORY = 50;

/**
 * Manages undo/redo history for the flow canvas.
 *
 * Usage:
 *   const { canUndo, canRedo, undo, redo, pushState } = useFlowHistory();
 *
 *   // After any user action that changes nodes/edges:
 *   pushState(currentNodes, currentEdges, "Added voice call node");
 *
 *   // On Ctrl+Z:
 *   const prev = undo();
 *   if (prev) { setNodes(prev.nodes); setEdges(prev.edges); }
 */
export function useFlowHistory() {
  const undoStack = useRef<HistoryEntry[]>([]);
  const redoStack = useRef<HistoryEntry[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const updateFlags = useCallback(() => {
    setCanUndo(undoStack.current.length > 0);
    setCanRedo(redoStack.current.length > 0);
  }, []);

  /** Snapshot current state before applying a change. */
  const pushState = useCallback(
    (nodes: Node[], edges: Edge[], label: string) => {
      undoStack.current.push({
        nodes: structuredClone(nodes),
        edges: structuredClone(edges),
        label,
      });
      // Trim history
      if (undoStack.current.length > MAX_HISTORY) {
        undoStack.current.shift();
      }
      // Any new action clears the redo stack
      redoStack.current = [];
      updateFlags();
    },
    [updateFlags],
  );

  /** Undo: pop from undo stack, push current state to redo stack. */
  const undo = useCallback(
    (currentNodes: Node[], currentEdges: Edge[]): HistoryEntry | null => {
      const entry = undoStack.current.pop();
      if (!entry) return null;
      // Push current state to redo
      redoStack.current.push({
        nodes: structuredClone(currentNodes),
        edges: structuredClone(currentEdges),
        label: "redo point",
      });
      updateFlags();
      return entry;
    },
    [updateFlags],
  );

  /** Redo: pop from redo stack, push current state to undo stack. */
  const redo = useCallback(
    (currentNodes: Node[], currentEdges: Edge[]): HistoryEntry | null => {
      const entry = redoStack.current.pop();
      if (!entry) return null;
      // Push current state to undo
      undoStack.current.push({
        nodes: structuredClone(currentNodes),
        edges: structuredClone(currentEdges),
        label: "undo point",
      });
      updateFlags();
      return entry;
    },
    [updateFlags],
  );

  /** Reset history (e.g., on fresh load). */
  const reset = useCallback(() => {
    undoStack.current = [];
    redoStack.current = [];
    updateFlags();
  }, [updateFlags]);

  return { canUndo, canRedo, pushState, undo, redo, reset };
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 5: Client-Side Flow Validation

**Files:**
- Create: `frontend/src/lib/flow-validation.ts`

- [ ] **Step 1: Create client-side validation matching server rules (spec §6)**

```typescript
// frontend/src/lib/flow-validation.ts
import type { Node, Edge } from "@xyflow/react";
import type { FlowNodeType, ValidationIssue, ValidationResult } from "./flow-types";

/**
 * Client-side flow validation — mirrors the server-side rules from spec §6.
 * Provides instant feedback before the user clicks Publish.
 */
export function validateFlowGraph(
  nodes: Node[],
  edges: Edge[],
): ValidationResult {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];

  if (nodes.length === 0) {
    errors.push({ message: "Flow has no nodes" });
    return { valid: false, errors, warnings };
  }

  // Build adjacency map
  const outgoing = new Map<string, Edge[]>();
  const incoming = new Map<string, Edge[]>();
  for (const edge of edges) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    outgoing.get(edge.source)!.push(edge);
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    incoming.get(edge.target)!.push(edge);
  }

  // Find entry node (node with no incoming edges, should be exactly 1)
  const entryNodes = nodes.filter((n) => !incoming.has(n.id) || incoming.get(n.id)!.length === 0);
  if (entryNodes.length === 0) {
    errors.push({ message: "No entry node found (every node has incoming edges — possible cycle)" });
  } else if (entryNodes.length > 1) {
    for (const en of entryNodes) {
      errors.push({ node_id: en.id, message: `Multiple entry points: "${en.data?.label || en.id}" has no incoming edges` });
    }
  }

  // Check every node is reachable from entry
  if (entryNodes.length === 1) {
    const reachable = new Set<string>();
    const queue = [entryNodes[0].id];
    while (queue.length > 0) {
      const current = queue.pop()!;
      if (reachable.has(current)) continue;
      reachable.add(current);
      const out = outgoing.get(current) || [];
      for (const e of out) {
        if (!reachable.has(e.target)) queue.push(e.target);
      }
    }
    for (const node of nodes) {
      if (!reachable.has(node.id)) {
        errors.push({ node_id: node.id, message: `Node "${node.data?.label || node.id}" is not reachable from the entry point` });
      }
    }
  }

  // Check every path eventually reaches an End node
  const endNodes = nodes.filter((n) => n.data?.nodeType === "end");
  if (endNodes.length === 0) {
    errors.push({ message: "Flow has no End node — every path must terminate" });
  }

  // Check for dead ends (non-end nodes with no outgoing edges)
  for (const node of nodes) {
    const nodeType = node.data?.nodeType as FlowNodeType | undefined;
    if (nodeType === "end") continue; // End nodes don't need outgoing edges
    const out = outgoing.get(node.id) || [];
    if (out.length === 0) {
      errors.push({ node_id: node.id, message: `Node "${node.data?.label || node.id}" is a dead end (no outgoing edges)` });
    }
  }

  // Condition nodes need at least 2 outgoing edges
  for (const node of nodes) {
    if (node.data?.nodeType === "condition") {
      const out = outgoing.get(node.id) || [];
      if (out.length < 2) {
        errors.push({ node_id: node.id, message: `Condition node "${node.data?.label || node.id}" needs at least 2 outgoing edges` });
      }
    }
  }

  // Action nodes need required config fields
  const ACTION_REQUIRED_FIELDS: Record<string, string[]> = {
    voice_call: ["bot_id"],
    whatsapp_template: ["template_name"],
    ai_generate_send: ["prompt"],
  };

  for (const node of nodes) {
    const nodeType = node.data?.nodeType as string;
    const required = ACTION_REQUIRED_FIELDS[nodeType];
    if (!required) continue;
    const config = node.data?.config as Record<string, any> | undefined;
    if (!config) {
      errors.push({ node_id: node.id, message: `Node "${node.data?.label || node.id}" has no configuration` });
      continue;
    }
    for (const field of required) {
      if (!config[field]) {
        errors.push({ node_id: node.id, message: `Node "${node.data?.label || node.id}" is missing required field: ${field}` });
      }
    }
  }

  // --- Warnings ---

  // Flows with no Goal Met nodes
  const goalNodes = nodes.filter((n) => n.data?.nodeType === "goal_met");
  if (goalNodes.length === 0) {
    warnings.push({ message: "Flow has no Goal Met nodes — consider adding one to track success" });
  }

  // Very short delays
  for (const node of nodes) {
    if (node.data?.nodeType === "delay_wait") {
      const config = node.data?.config as Record<string, any> | undefined;
      if (config) {
        const minutes =
          config.duration_unit === "minutes"
            ? config.duration_value
            : config.duration_unit === "hours"
              ? config.duration_value * 60
              : config.duration_value * 1440;
        if (minutes < 5) {
          warnings.push({ node_id: node.id, message: `Delay "${node.data?.label || node.id}" is very short (${minutes} min) — may cause rapid retries` });
        }
      }
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 6: Flow Templates

**Files:**
- Create: `frontend/src/lib/flow-templates.ts`

- [ ] **Step 1: Define flow templates as pre-built node/edge structures**

```typescript
// frontend/src/lib/flow-templates.ts
import type { FlowNodeType } from "./flow-types";
import { getDefaultConfig } from "./flow-types";

export interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  icon: string; // lucide icon name
  nodes: TemplateNode[];
  edges: TemplateEdge[];
}

interface TemplateNode {
  temp_id: string; // temporary ID for wiring edges within template
  node_type: FlowNodeType;
  name: string;
  position_x: number;
  position_y: number;
  config: Record<string, any>;
}

interface TemplateEdge {
  source_temp_id: string;
  target_temp_id: string;
  condition_label: string;
}

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "blank",
    name: "Blank Flow",
    description: "Start with just an entry point and an end node",
    icon: "FileText",
    nodes: [
      { temp_id: "n1", node_type: "delay_wait", name: "Start", position_x: 300, position_y: 50, config: { duration_value: 0, duration_unit: "minutes", send_window: { enabled: false, resume_at: "09:00", days: [], timezone: "Asia/Kolkata" } } },
      { temp_id: "n2", node_type: "end", name: "End", position_x: 300, position_y: 250, config: { end_reason: "completed" } },
    ],
    edges: [
      { source_temp_id: "n1", target_temp_id: "n2", condition_label: "completed" },
    ],
  },
  {
    id: "post_call_followup",
    name: "Post-Call Follow-Up",
    description: "Call, then branch on outcome — WhatsApp for interested, retry for no answer",
    icon: "PhoneForwarded",
    nodes: [
      { temp_id: "n1", node_type: "voice_call", name: "Initial Call", position_x: 300, position_y: 50, config: getDefaultConfig("voice_call") },
      { temp_id: "n2", node_type: "condition", name: "Interested?", position_x: 300, position_y: 200, config: { conditions: [{ label: "interested", rules: [{ field: "interest_level", operator: "gte", value: 7 }] }], default_label: "not_interested" } },
      { temp_id: "n3", node_type: "whatsapp_template", name: "Send Follow-Up", position_x: 100, position_y: 350, config: getDefaultConfig("whatsapp_template") },
      { temp_id: "n4", node_type: "delay_wait", name: "Wait 2h", position_x: 500, position_y: 350, config: { duration_value: 2, duration_unit: "hours", send_window: { enabled: false, resume_at: "09:00", days: [], timezone: "Asia/Kolkata" } } },
      { temp_id: "n5", node_type: "voice_call", name: "Retry Call", position_x: 500, position_y: 500, config: getDefaultConfig("voice_call") },
      { temp_id: "n6", node_type: "goal_met", name: "Interested", position_x: 100, position_y: 500, config: { goal_name: "interested", goal_description: "Lead expressed interest" } },
      { temp_id: "n7", node_type: "end", name: "End", position_x: 300, position_y: 650, config: { end_reason: "completed" } },
    ],
    edges: [
      { source_temp_id: "n1", target_temp_id: "n2", condition_label: "picked_up" },
      { source_temp_id: "n1", target_temp_id: "n4", condition_label: "no_answer" },
      { source_temp_id: "n1", target_temp_id: "n7", condition_label: "failed" },
      { source_temp_id: "n2", target_temp_id: "n3", condition_label: "interested" },
      { source_temp_id: "n2", target_temp_id: "n7", condition_label: "not_interested" },
      { source_temp_id: "n3", target_temp_id: "n6", condition_label: "sent" },
      { source_temp_id: "n4", target_temp_id: "n5", condition_label: "completed" },
      { source_temp_id: "n5", target_temp_id: "n2", condition_label: "picked_up" },
      { source_temp_id: "n5", target_temp_id: "n7", condition_label: "failed" },
      { source_temp_id: "n6", target_temp_id: "n7", condition_label: "continue" },
    ],
  },
  {
    id: "no_answer_recovery",
    name: "No-Answer Recovery",
    description: "Call, then WhatsApp + delay + retry for no-answer leads",
    icon: "PhoneMissed",
    nodes: [
      { temp_id: "n1", node_type: "voice_call", name: "Initial Call", position_x: 300, position_y: 50, config: getDefaultConfig("voice_call") },
      { temp_id: "n2", node_type: "whatsapp_template", name: "WhatsApp Nudge", position_x: 300, position_y: 200, config: getDefaultConfig("whatsapp_template") },
      { temp_id: "n3", node_type: "delay_wait", name: "Wait 4h", position_x: 300, position_y: 350, config: { duration_value: 4, duration_unit: "hours", send_window: { enabled: true, resume_at: "09:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"], timezone: "Asia/Kolkata" } } },
      { temp_id: "n4", node_type: "voice_call", name: "Retry Call", position_x: 300, position_y: 500, config: getDefaultConfig("voice_call") },
      { temp_id: "n5", node_type: "goal_met", name: "Connected", position_x: 100, position_y: 350, config: { goal_name: "connected", goal_description: "Lead picked up the call" } },
      { temp_id: "n6", node_type: "end", name: "End", position_x: 300, position_y: 650, config: { end_reason: "completed" } },
    ],
    edges: [
      { source_temp_id: "n1", target_temp_id: "n5", condition_label: "picked_up" },
      { source_temp_id: "n1", target_temp_id: "n2", condition_label: "no_answer" },
      { source_temp_id: "n1", target_temp_id: "n6", condition_label: "failed" },
      { source_temp_id: "n2", target_temp_id: "n3", condition_label: "sent" },
      { source_temp_id: "n2", target_temp_id: "n6", condition_label: "failed" },
      { source_temp_id: "n3", target_temp_id: "n4", condition_label: "completed" },
      { source_temp_id: "n4", target_temp_id: "n5", condition_label: "picked_up" },
      { source_temp_id: "n4", target_temp_id: "n6", condition_label: "no_answer" },
      { source_temp_id: "n4", target_temp_id: "n6", condition_label: "failed" },
      { source_temp_id: "n5", target_temp_id: "n6", condition_label: "continue" },
    ],
  },
  {
    id: "lead_nurture",
    name: "Lead Nurture",
    description: "Condition on interest, then AI-personalized messages with timed follow-ups",
    icon: "Sprout",
    nodes: [
      { temp_id: "n1", node_type: "condition", name: "Interest Level", position_x: 300, position_y: 50, config: { conditions: [{ label: "high", rules: [{ field: "interest_level", operator: "gte", value: 7 }] }, { label: "medium", rules: [{ field: "interest_level", operator: "gte", value: 4 }] }], default_label: "low" } },
      { temp_id: "n2", node_type: "ai_generate_send", name: "Personalized Message", position_x: 100, position_y: 200, config: { ...getDefaultConfig("ai_generate_send"), prompt: "Write a warm follow-up for {{contact_name}} who showed high interest in coaching." } },
      { temp_id: "n3", node_type: "delay_wait", name: "Wait 1 Day", position_x: 300, position_y: 200, config: { duration_value: 1, duration_unit: "days", send_window: { enabled: true, resume_at: "09:00", days: ["mon", "tue", "wed", "thu", "fri"], timezone: "Asia/Kolkata" } } },
      { temp_id: "n4", node_type: "whatsapp_template", name: "Gentle Reminder", position_x: 300, position_y: 350, config: getDefaultConfig("whatsapp_template") },
      { temp_id: "n5", node_type: "goal_met", name: "Engaged", position_x: 100, position_y: 350, config: { goal_name: "engaged", goal_description: "Lead engaged with follow-up content" } },
      { temp_id: "n6", node_type: "end", name: "End", position_x: 300, position_y: 500, config: { end_reason: "completed" } },
    ],
    edges: [
      { source_temp_id: "n1", target_temp_id: "n2", condition_label: "high" },
      { source_temp_id: "n1", target_temp_id: "n3", condition_label: "medium" },
      { source_temp_id: "n1", target_temp_id: "n6", condition_label: "low" },
      { source_temp_id: "n2", target_temp_id: "n5", condition_label: "sent" },
      { source_temp_id: "n2", target_temp_id: "n6", condition_label: "failed" },
      { source_temp_id: "n3", target_temp_id: "n4", condition_label: "completed" },
      { source_temp_id: "n4", target_temp_id: "n6", condition_label: "sent" },
      { source_temp_id: "n4", target_temp_id: "n6", condition_label: "failed" },
      { source_temp_id: "n5", target_temp_id: "n6", condition_label: "continue" },
    ],
  },
];
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 7: Base Node Component

**Files:**
- Create: `frontend/src/components/flow/nodes/BaseNode.tsx`

- [ ] **Step 1: Create the shared base wrapper for all custom nodes**

```tsx
// frontend/src/components/flow/nodes/BaseNode.tsx
"use client";

import { memo, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import {
  Phone,
  MessageSquare,
  MessageCircle,
  Sparkles,
  GitBranch,
  Clock,
  Bell,
  Target,
  CircleStop,
} from "lucide-react";
import type { FlowNodeType } from "@/lib/flow-types";
import { NODE_TYPE_REGISTRY } from "@/lib/flow-types";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Phone,
  MessageSquare,
  MessageCircle,
  Sparkles,
  GitBranch,
  Clock,
  Bell,
  Target,
  CircleStop,
};

export interface BaseNodeData {
  label: string;
  nodeType: FlowNodeType;
  config: Record<string, any>;
  isSelected?: boolean;
  stats?: { passed?: number; failed?: number }; // analytics badge
  [key: string]: unknown;
}

interface BaseNodeProps {
  data: BaseNodeData;
  selected: boolean;
  children?: ReactNode;
  /** Custom output handles — if not provided, renders a single bottom handle */
  outputHandles?: ReactNode;
}

function BaseNodeComponent({ data, selected, children, outputHandles }: BaseNodeProps) {
  const info = NODE_TYPE_REGISTRY.find((n) => n.type === data.nodeType);
  const IconComponent = info ? ICON_MAP[info.icon] : null;
  const colorClass = info?.color ?? "border-gray-400";

  return (
    <div
      className={cn(
        "min-w-[220px] rounded-lg border-2 bg-card px-3 py-2 shadow-sm transition-shadow",
        colorClass,
        selected && "ring-2 ring-primary ring-offset-2",
      )}
    >
      {/* Input handle */}
      {data.nodeType !== "delay_wait" || data.label !== "Start" ? (
        <Handle
          type="target"
          position={Position.Top}
          className="!h-3 !w-3 !border-2 !border-background !bg-muted-foreground"
        />
      ) : null}

      {/* Header */}
      <div className="flex items-center gap-2">
        {IconComponent && (
          <IconComponent className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate text-sm font-medium">{data.label}</span>
      </div>

      {/* Body — node-specific content */}
      {children && <div className="mt-1.5 text-xs text-muted-foreground">{children}</div>}

      {/* Analytics badge */}
      {data.stats && (data.stats.passed != null || data.stats.failed != null) && (
        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
          {data.stats.passed != null && (
            <span className="text-emerald-500">{data.stats.passed} passed</span>
          )}
          {data.stats.passed != null && data.stats.failed != null && <span>/</span>}
          {data.stats.failed != null && (
            <span className="text-red-400">{data.stats.failed} failed</span>
          )}
        </div>
      )}

      {/* Output handles */}
      {outputHandles ?? (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!h-3 !w-3 !border-2 !border-background !bg-muted-foreground"
        />
      )}
    </div>
  );
}

export const BaseNode = memo(BaseNodeComponent);
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 8: Custom Node Components

**Files:**
- Create: `frontend/src/components/flow/nodes/VoiceCallNode.tsx`
- Create: `frontend/src/components/flow/nodes/WhatsAppTemplateNode.tsx`
- Create: `frontend/src/components/flow/nodes/WhatsAppSessionNode.tsx`
- Create: `frontend/src/components/flow/nodes/AIGenerateNode.tsx`
- Create: `frontend/src/components/flow/nodes/ConditionNode.tsx`
- Create: `frontend/src/components/flow/nodes/DelayWaitNode.tsx`
- Create: `frontend/src/components/flow/nodes/WaitForEventNode.tsx`
- Create: `frontend/src/components/flow/nodes/GoalMetNode.tsx`
- Create: `frontend/src/components/flow/nodes/EndNode.tsx`

- [ ] **Step 1: Create VoiceCallNode — shows bot name and retry config**

```tsx
// frontend/src/components/flow/nodes/VoiceCallNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";
import { NODE_EDGE_LABELS } from "@/lib/flow-types";

function VoiceCallNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  const handles = NODE_EDGE_LABELS.voice_call;

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="flex justify-between px-1 pt-1">
          {handles.map((label, i) => (
            <Handle
              key={label}
              type="source"
              position={Position.Bottom}
              id={label}
              className="!h-2.5 !w-2.5 !border-2 !border-background !bg-muted-foreground"
              style={{ left: `${((i + 1) / (handles.length + 1)) * 100}%` }}
              title={label}
            />
          ))}
        </div>
      }
    >
      {config.bot_id ? (
        <span>Bot configured</span>
      ) : (
        <span className="text-amber-500">No bot selected</span>
      )}
      {config.quick_retry?.enabled && (
        <div>Retry: {config.quick_retry.max_attempts}x every {config.quick_retry.interval_hours}h</div>
      )}
    </BaseNode>
  );
}

export const VoiceCallNode = memo(VoiceCallNodeComponent);
```

- [ ] **Step 2: Create WhatsAppTemplateNode**

```tsx
// frontend/src/components/flow/nodes/WhatsAppTemplateNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function WhatsAppTemplateNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="flex justify-around px-1 pt-1">
          {["sent", "failed"].map((label) => (
            <Handle key={label} type="source" position={Position.Bottom} id={label}
              className="!h-2.5 !w-2.5 !border-2 !border-background !bg-muted-foreground"
              title={label}
            />
          ))}
        </div>
      }
    >
      {config.template_name ? (
        <span>Template: {config.template_name}</span>
      ) : (
        <span className="text-amber-500">No template selected</span>
      )}
    </BaseNode>
  );
}

export const WhatsAppTemplateNode = memo(WhatsAppTemplateNodeComponent);
```

- [ ] **Step 3: Create WhatsAppSessionNode**

```tsx
// frontend/src/components/flow/nodes/WhatsAppSessionNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function WhatsAppSessionNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;
  const handles = ["sent", "replied", "expired", "failed"];

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="flex justify-between px-1 pt-1">
          {handles.map((label, i) => (
            <Handle key={label} type="source" position={Position.Bottom} id={label}
              className="!h-2.5 !w-2.5 !border-2 !border-background !bg-muted-foreground"
              style={{ left: `${((i + 1) / (handles.length + 1)) * 100}%` }}
              title={label}
            />
          ))}
        </div>
      }
    >
      {config.ai_generation?.enabled ? (
        <span>AI-generated message</span>
      ) : config.message ? (
        <span className="truncate">{config.message.slice(0, 40)}...</span>
      ) : (
        <span className="text-amber-500">No message configured</span>
      )}
      {config.expects_reply && <div>Expects reply</div>}
    </BaseNode>
  );
}

export const WhatsAppSessionNode = memo(WhatsAppSessionNodeComponent);
```

- [ ] **Step 4: Create AIGenerateNode**

```tsx
// frontend/src/components/flow/nodes/AIGenerateNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function AIGenerateNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="flex justify-around px-1 pt-1">
          {["sent", "failed"].map((label) => (
            <Handle key={label} type="source" position={Position.Bottom} id={label}
              className="!h-2.5 !w-2.5 !border-2 !border-background !bg-muted-foreground"
              title={label}
            />
          ))}
        </div>
      }
    >
      <span>
        {config.mode === "fill_template_vars" ? "Fill template vars" : "Full message"}
        {" via "}{config.send_via === "whatsapp_template" ? "WA template" : "WA session"}
      </span>
      {config.prompt ? (
        <div className="truncate">{config.prompt.slice(0, 50)}...</div>
      ) : (
        <div className="text-amber-500">No prompt set</div>
      )}
    </BaseNode>
  );
}

export const AIGenerateNode = memo(AIGenerateNodeComponent);
```

- [ ] **Step 5: Create ConditionNode — shows branch labels as output handles**

```tsx
// frontend/src/components/flow/nodes/ConditionNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function ConditionNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;
  const branches: string[] = [
    ...(config.conditions || []).map((c: any) => c.label),
    config.default_label || "other",
  ];

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="mt-1 flex flex-wrap justify-between gap-0.5 px-1 pt-1">
          {branches.map((label, i) => (
            <div key={label} className="relative flex flex-col items-center">
              <span className="mb-0.5 text-[9px] text-muted-foreground">{label}</span>
              <Handle
                type="source"
                position={Position.Bottom}
                id={label}
                className="!relative !left-0 !top-0 !h-2.5 !w-2.5 !translate-x-0 !translate-y-0 !border-2 !border-background !bg-muted-foreground"
                title={label}
              />
            </div>
          ))}
        </div>
      }
    >
      {branches.length <= 1 ? (
        <span className="text-amber-500">No conditions defined</span>
      ) : (
        <span>{branches.length} branches</span>
      )}
    </BaseNode>
  );
}

export const ConditionNode = memo(ConditionNodeComponent);
```

- [ ] **Step 6: Create DelayWaitNode**

```tsx
// frontend/src/components/flow/nodes/DelayWaitNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function DelayWaitNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <Handle
          type="source"
          position={Position.Bottom}
          id="completed"
          className="!h-3 !w-3 !border-2 !border-background !bg-muted-foreground"
          title="completed"
        />
      }
    >
      <span>
        Wait {config.duration_value} {config.duration_unit}
      </span>
      {config.send_window?.enabled && (
        <div>Resume at {config.send_window.resume_at}</div>
      )}
    </BaseNode>
  );
}

export const DelayWaitNode = memo(DelayWaitNodeComponent);
```

- [ ] **Step 7: Create WaitForEventNode**

```tsx
// frontend/src/components/flow/nodes/WaitForEventNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function WaitForEventNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;
  const handles = [config.event_type || "event", config.timeout_label || "timed_out"];

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <div className="flex justify-around px-1 pt-1">
          {handles.map((label: string) => (
            <div key={label} className="relative flex flex-col items-center">
              <span className="mb-0.5 text-[9px] text-muted-foreground">{label}</span>
              <Handle
                type="source"
                position={Position.Bottom}
                id={label}
                className="!relative !left-0 !top-0 !h-2.5 !w-2.5 !translate-x-0 !translate-y-0 !border-2 !border-background !bg-muted-foreground"
                title={label}
              />
            </div>
          ))}
        </div>
      }
    >
      <span>Wait for: {config.event_type?.replace("_", " ") || "event"}</span>
      <div>Timeout: {config.timeout_hours || 24}h</div>
    </BaseNode>
  );
}

export const WaitForEventNode = memo(WaitForEventNodeComponent);
```

- [ ] **Step 8: Create GoalMetNode**

```tsx
// frontend/src/components/flow/nodes/GoalMetNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function GoalMetNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  return (
    <BaseNode
      data={d}
      selected={selected ?? false}
      outputHandles={
        <Handle
          type="source"
          position={Position.Bottom}
          id="continue"
          className="!h-3 !w-3 !border-2 !border-background !bg-muted-foreground"
          title="continue"
        />
      }
    >
      {config.goal_name ? (
        <span className="font-medium text-emerald-500">{config.goal_name}</span>
      ) : (
        <span className="text-amber-500">No goal defined</span>
      )}
    </BaseNode>
  );
}

export const GoalMetNode = memo(GoalMetNodeComponent);
```

- [ ] **Step 9: Create EndNode**

```tsx
// frontend/src/components/flow/nodes/EndNode.tsx
"use client";

import { memo } from "react";
import type { NodeProps } from "@xyflow/react";
import { BaseNode, type BaseNodeData } from "./BaseNode";

function EndNodeComponent({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const config = d.config as Record<string, any>;

  return (
    <BaseNode data={d} selected={selected ?? false} outputHandles={<></>}>
      <span className="capitalize">{config.end_reason || "completed"}</span>
    </BaseNode>
  );
}

export const EndNode = memo(EndNodeComponent);
```

- [ ] **Step 10: Verify all node components compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 9: Node Palette (Left Sidebar)

**Files:**
- Create: `frontend/src/components/flow/NodePalette.tsx`

- [ ] **Step 1: Create the draggable node palette grouped by category**

```tsx
// frontend/src/components/flow/NodePalette.tsx
"use client";

import { type DragEvent, useCallback } from "react";
import {
  Phone,
  MessageSquare,
  MessageCircle,
  Sparkles,
  GitBranch,
  Clock,
  Bell,
  Target,
  CircleStop,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NODE_TYPE_REGISTRY, type FlowNodeType } from "@/lib/flow-types";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Phone, MessageSquare, MessageCircle, Sparkles, GitBranch, Clock, Bell, Target, CircleStop,
};

const CATEGORIES = [
  { key: "action" as const, label: "Actions" },
  { key: "control" as const, label: "Control" },
  { key: "terminal" as const, label: "Terminal" },
];

interface NodePaletteProps {
  className?: string;
}

export function NodePalette({ className }: NodePaletteProps) {
  const onDragStart = useCallback(
    (event: DragEvent<HTMLDivElement>, nodeType: FlowNodeType) => {
      event.dataTransfer.setData("application/reactflow-nodetype", nodeType);
      event.dataTransfer.effectAllowed = "move";
    },
    [],
  );

  return (
    <div className={cn("flex w-56 flex-col gap-4 border-r bg-background p-4", className)}>
      <h3 className="text-sm font-semibold text-foreground">Nodes</h3>
      {CATEGORIES.map((cat) => {
        const items = NODE_TYPE_REGISTRY.filter((n) => n.category === cat.key);
        return (
          <div key={cat.key}>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {cat.label}
            </p>
            <div className="flex flex-col gap-1">
              {items.map((info) => {
                const Icon = ICON_MAP[info.icon];
                return (
                  <div
                    key={info.type}
                    draggable
                    onDragStart={(e) => onDragStart(e, info.type)}
                    className={cn(
                      "flex cursor-grab items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm transition-colors hover:bg-accent active:cursor-grabbing",
                      info.color,
                    )}
                    title={info.description}
                  >
                    {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                    <span className="truncate">{info.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 10: Properties Panel (Right Sidebar)

**Files:**
- Create: `frontend/src/components/flow/PropertiesPanel.tsx`

- [ ] **Step 1: Create the properties panel that shows config for the selected node**

```tsx
// frontend/src/components/flow/PropertiesPanel.tsx
"use client";

import { useCallback } from "react";
import type { Node } from "@xyflow/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { FlowNodeType } from "@/lib/flow-types";

interface PropertiesPanelProps {
  node: Node | null;
  onClose: () => void;
  onUpdateNode: (nodeId: string, updates: Partial<Node["data"]>) => void;
  bots: Array<{ id: string; name: string }>;
  className?: string;
}

export function PropertiesPanel({
  node,
  onClose,
  onUpdateNode,
  bots,
  className,
}: PropertiesPanelProps) {
  const updateConfig = useCallback(
    (key: string, value: any) => {
      if (!node) return;
      const newConfig = { ...(node.data.config as Record<string, any>), [key]: value };
      onUpdateNode(node.id, { config: newConfig });
    },
    [node, onUpdateNode],
  );

  const updateNestedConfig = useCallback(
    (parentKey: string, key: string, value: any) => {
      if (!node) return;
      const config = node.data.config as Record<string, any>;
      const newParent = { ...(config[parentKey] || {}), [key]: value };
      const newConfig = { ...config, [parentKey]: newParent };
      onUpdateNode(node.id, { config: newConfig });
    },
    [node, onUpdateNode],
  );

  if (!node) return null;

  const nodeType = node.data.nodeType as FlowNodeType;
  const config = node.data.config as Record<string, any>;

  return (
    <div className={cn("flex w-80 flex-col border-l bg-background", className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold">Properties</h3>
          <p className="text-xs text-muted-foreground capitalize">{nodeType.replace("_", " ")}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          {/* Node name — shared across all types */}
          <div>
            <Label className="text-xs">Node Name</Label>
            <Input
              value={(node.data.label as string) || ""}
              onChange={(e) => onUpdateNode(node.id, { label: e.target.value })}
              className="mt-1 h-8 text-sm"
            />
          </div>

          {/* Type-specific config */}
          {nodeType === "voice_call" && (
            <>
              <div>
                <Label className="text-xs">Bot</Label>
                <Select
                  value={config.bot_id || ""}
                  onValueChange={(v) => updateConfig("bot_id", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue placeholder="Select a bot" />
                  </SelectTrigger>
                  <SelectContent>
                    {bots.map((bot) => (
                      <SelectItem key={bot.id} value={bot.id}>
                        {bot.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs">Quick Retry</Label>
                <Switch
                  checked={config.quick_retry?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("quick_retry", "enabled", v)}
                />
              </div>
              {config.quick_retry?.enabled && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Max Attempts</Label>
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      value={config.quick_retry.max_attempts ?? 3}
                      onChange={(e) => updateNestedConfig("quick_retry", "max_attempts", parseInt(e.target.value) || 3)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Interval (hrs)</Label>
                    <Input
                      type="number"
                      min={0.5}
                      step={0.5}
                      value={config.quick_retry.interval_hours ?? 1}
                      onChange={(e) => updateNestedConfig("quick_retry", "interval_hours", parseFloat(e.target.value) || 1)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                </div>
              )}
            </>
          )}

          {nodeType === "whatsapp_template" && (
            <>
              <div>
                <Label className="text-xs">Template Name</Label>
                <Input
                  value={config.template_name || ""}
                  onChange={(e) => updateConfig("template_name", e.target.value)}
                  className="mt-1 h-8 text-sm"
                  placeholder="e.g., follow_up_v1"
                />
              </div>
            </>
          )}

          {nodeType === "whatsapp_session" && (
            <>
              <div className="flex items-center justify-between">
                <Label className="text-xs">AI Generation</Label>
                <Switch
                  checked={config.ai_generation?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("ai_generation", "enabled", v)}
                />
              </div>
              {config.ai_generation?.enabled ? (
                <div>
                  <Label className="text-xs">AI Prompt</Label>
                  <Textarea
                    value={config.ai_generation.prompt || ""}
                    onChange={(e) => updateNestedConfig("ai_generation", "prompt", e.target.value)}
                    className="mt-1 min-h-[80px] text-sm"
                    placeholder="Write a follow-up for {{contact_name}}..."
                  />
                </div>
              ) : (
                <div>
                  <Label className="text-xs">Static Message</Label>
                  <Textarea
                    value={config.message || ""}
                    onChange={(e) => updateConfig("message", e.target.value)}
                    className="mt-1 min-h-[80px] text-sm"
                    placeholder="Hi {{contact_name}}..."
                  />
                </div>
              )}
              <div className="flex items-center justify-between">
                <Label className="text-xs">Expects Reply</Label>
                <Switch
                  checked={config.expects_reply ?? false}
                  onCheckedChange={(v) => updateConfig("expects_reply", v)}
                />
              </div>
            </>
          )}

          {nodeType === "ai_generate_send" && (
            <>
              <div>
                <Label className="text-xs">Mode</Label>
                <Select
                  value={config.mode || "full_message"}
                  onValueChange={(v) => updateConfig("mode", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="full_message">Full Message</SelectItem>
                    <SelectItem value="fill_template_vars">Fill Template Vars</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Prompt</Label>
                <Textarea
                  value={config.prompt || ""}
                  onChange={(e) => updateConfig("prompt", e.target.value)}
                  className="mt-1 min-h-[80px] text-sm"
                  placeholder="Generate a message for {{contact_name}}..."
                />
              </div>
              <div>
                <Label className="text-xs">Send Via</Label>
                <Select
                  value={config.send_via || "whatsapp_session"}
                  onValueChange={(v) => updateConfig("send_via", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="whatsapp_session">WhatsApp Session</SelectItem>
                    <SelectItem value="whatsapp_template">WhatsApp Template</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {nodeType === "condition" && (
            <>
              <p className="text-xs text-muted-foreground">
                Condition branches are configured as outgoing edges. Add rules to determine which branch a lead follows.
              </p>
              <div>
                <Label className="text-xs">Default Branch Label</Label>
                <Input
                  value={config.default_label || "other"}
                  onChange={(e) => updateConfig("default_label", e.target.value)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
              {/* Full condition editor is complex — placeholder for v1 */}
              <p className="text-[11px] text-muted-foreground italic">
                Condition rules editor coming in next iteration. Use JSON config for now.
              </p>
            </>
          )}

          {nodeType === "delay_wait" && (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Duration</Label>
                <Input
                  type="number"
                  min={0}
                  value={config.duration_value ?? 1}
                  onChange={(e) => updateConfig("duration_value", parseInt(e.target.value) || 1)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
              <div>
                <Label className="text-xs">Unit</Label>
                <Select
                  value={config.duration_unit || "hours"}
                  onValueChange={(v) => updateConfig("duration_unit", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="minutes">Minutes</SelectItem>
                    <SelectItem value="hours">Hours</SelectItem>
                    <SelectItem value="days">Days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {nodeType === "wait_for_event" && (
            <>
              <div>
                <Label className="text-xs">Event Type</Label>
                <Select
                  value={config.event_type || "reply_received"}
                  onValueChange={(v) => updateConfig("event_type", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="reply_received">Reply Received</SelectItem>
                    <SelectItem value="call_completed">Call Completed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Timeout (hours)</Label>
                <Input
                  type="number"
                  min={1}
                  value={config.timeout_hours ?? 24}
                  onChange={(e) => updateConfig("timeout_hours", parseInt(e.target.value) || 24)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
            </>
          )}

          {nodeType === "goal_met" && (
            <>
              <div>
                <Label className="text-xs">Goal Name</Label>
                <Input
                  value={config.goal_name || ""}
                  onChange={(e) => updateConfig("goal_name", e.target.value)}
                  className="mt-1 h-8 text-sm"
                  placeholder="e.g., booking_confirmed"
                />
              </div>
              <div>
                <Label className="text-xs">Description</Label>
                <Textarea
                  value={config.goal_description || ""}
                  onChange={(e) => updateConfig("goal_description", e.target.value)}
                  className="mt-1 min-h-[60px] text-sm"
                  placeholder="What does this goal represent?"
                />
              </div>
            </>
          )}

          {nodeType === "end" && (
            <div>
              <Label className="text-xs">End Reason</Label>
              <Select
                value={config.end_reason || "completed"}
                onValueChange={(v) => updateConfig("end_reason", v)}
              >
                <SelectTrigger className="mt-1 h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="disqualified">Disqualified</SelectItem>
                  <SelectItem value="unresponsive">Unresponsive</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Send window — shared by action nodes */}
          {["voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send", "delay_wait"].includes(nodeType) && (
            <div className="border-t pt-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">Send Window</Label>
                <Switch
                  checked={config.send_window?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("send_window", "enabled", v)}
                />
              </div>
              {config.send_window?.enabled && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Start</Label>
                    <Input
                      type="time"
                      value={config.send_window.start || config.send_window.resume_at || "09:00"}
                      onChange={(e) => {
                        updateNestedConfig("send_window", "start", e.target.value);
                        updateNestedConfig("send_window", "resume_at", e.target.value);
                      }}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">End</Label>
                    <Input
                      type="time"
                      value={config.send_window.end || "19:00"}
                      onChange={(e) => updateNestedConfig("send_window", "end", e.target.value)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 11: Canvas Toolbar

**Files:**
- Create: `frontend/src/components/flow/CanvasToolbar.tsx`

- [ ] **Step 1: Create the top toolbar with undo/redo, zoom, validate, and publish**

```tsx
// frontend/src/components/flow/CanvasToolbar.tsx
"use client";

import { useReactFlow } from "@xyflow/react";
import {
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  LayoutGrid,
  CheckCircle2,
  Rocket,
  Play,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CanvasToolbarProps {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onAutoLayout: () => void;
  onValidate: () => void;
  onPublish: () => void;
  onSimulate: () => void;
  isPublishing: boolean;
  isValidating: boolean;
  isDraft: boolean;
}

export function CanvasToolbar({
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onAutoLayout,
  onValidate,
  onPublish,
  onSimulate,
  isPublishing,
  isValidating,
  isDraft,
}: CanvasToolbarProps) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex items-center gap-1 rounded-lg border bg-background/95 px-2 py-1 shadow-sm backdrop-blur">
        {/* Undo/Redo */}
        <ToolbarButton icon={Undo2} label="Undo (Ctrl+Z)" onClick={onUndo} disabled={!canUndo} />
        <ToolbarButton icon={Redo2} label="Redo (Ctrl+Y)" onClick={onRedo} disabled={!canRedo} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Zoom */}
        <ToolbarButton icon={ZoomIn} label="Zoom In" onClick={() => zoomIn()} />
        <ToolbarButton icon={ZoomOut} label="Zoom Out" onClick={() => zoomOut()} />
        <ToolbarButton icon={Maximize2} label="Fit View" onClick={() => fitView({ padding: 0.2 })} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Layout */}
        <ToolbarButton icon={LayoutGrid} label="Auto Layout" onClick={onAutoLayout} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Actions */}
        <ToolbarButton
          icon={Play}
          label="Simulate"
          onClick={onSimulate}
        />

        <ToolbarButton
          icon={isValidating ? Loader2 : CheckCircle2}
          label="Validate"
          onClick={onValidate}
          disabled={isValidating}
          iconClassName={isValidating ? "animate-spin" : ""}
        />

        {isDraft && (
          <Button
            size="sm"
            onClick={onPublish}
            disabled={isPublishing}
            className="ml-1 h-7 gap-1.5 px-3 text-xs"
          >
            {isPublishing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Rocket className="h-3.5 w-3.5" />
            )}
            Publish
          </Button>
        )}
      </div>
    </TooltipProvider>
  );
}

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  iconClassName,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  iconClassName?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClick}
          disabled={disabled}
          className="h-7 w-7 p-0"
        >
          <Icon className={`h-4 w-4 ${iconClassName || ""}`} />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 12: Validation Panel

**Files:**
- Create: `frontend/src/components/flow/ValidationPanel.tsx`

- [ ] **Step 1: Create the validation results display**

```tsx
// frontend/src/components/flow/ValidationPanel.tsx
"use client";

import { AlertTriangle, XCircle, CheckCircle2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ValidationResult } from "@/lib/flow-types";

interface ValidationPanelProps {
  result: ValidationResult | null;
  onClose: () => void;
  onFocusNode: (nodeId: string) => void;
}

export function ValidationPanel({ result, onClose, onFocusNode }: ValidationPanelProps) {
  if (!result) return null;

  return (
    <div className="absolute bottom-4 left-1/2 z-10 w-[420px] -translate-x-1/2 rounded-lg border bg-background shadow-lg">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          {result.valid ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <XCircle className="h-4 w-4 text-red-500" />
          )}
          <span className="text-sm font-medium">
            {result.valid ? "Validation passed" : `${result.errors.length} error(s) found`}
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-6 w-6 p-0">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="max-h-48 overflow-y-auto p-2">
        {result.errors.map((issue, i) => (
          <button
            key={`err-${i}`}
            className={cn(
              "flex w-full items-start gap-2 rounded-md px-3 py-1.5 text-left text-xs hover:bg-accent",
              issue.node_id && "cursor-pointer",
            )}
            onClick={() => issue.node_id && onFocusNode(issue.node_id)}
          >
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
            <span>{issue.message}</span>
          </button>
        ))}
        {result.warnings.map((issue, i) => (
          <button
            key={`warn-${i}`}
            className={cn(
              "flex w-full items-start gap-2 rounded-md px-3 py-1.5 text-left text-xs hover:bg-accent",
              issue.node_id && "cursor-pointer",
            )}
            onClick={() => issue.node_id && onFocusNode(issue.node_id)}
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span>{issue.message}</span>
          </button>
        ))}
        {result.errors.length === 0 && result.warnings.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No issues found. Ready to publish.</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 13: Template Picker Dialog

**Files:**
- Create: `frontend/src/components/flow/TemplatePicker.tsx`

- [ ] **Step 1: Create the template picker shown on "Create New Flow"**

```tsx
// frontend/src/components/flow/TemplatePicker.tsx
"use client";

import { useState } from "react";
import {
  FileText,
  PhoneForwarded,
  PhoneMissed,
  Sprout,
  Loader2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { FLOW_TEMPLATES, type FlowTemplate } from "@/lib/flow-templates";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  FileText, PhoneForwarded, PhoneMissed, Sprout,
};

interface TemplatePickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, templateId: string) => Promise<void>;
}

export function TemplatePicker({ open, onOpenChange, onCreate }: TemplatePickerProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<string>("blank");
  const [flowName, setFlowName] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!flowName.trim()) return;
    setCreating(true);
    try {
      await onCreate(flowName.trim(), selectedTemplate);
      setFlowName("");
      setSelectedTemplate("blank");
      onOpenChange(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create New Flow</DialogTitle>
          <DialogDescription>
            Choose a template to get started, or begin with a blank flow.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label className="text-sm">Flow Name</Label>
            <Input
              value={flowName}
              onChange={(e) => setFlowName(e.target.value)}
              placeholder="e.g., Post-Call Follow-Up"
              className="mt-1"
              autoFocus
            />
          </div>

          <div>
            <Label className="text-sm">Template</Label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {FLOW_TEMPLATES.map((tmpl) => {
                const Icon = ICON_MAP[tmpl.icon] || FileText;
                return (
                  <button
                    key={tmpl.id}
                    onClick={() => setSelectedTemplate(tmpl.id)}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent",
                      selectedTemplate === tmpl.id && "border-primary bg-accent",
                    )}
                  >
                    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{tmpl.name}</p>
                      <p className="text-xs text-muted-foreground">{tmpl.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <Button
            onClick={handleCreate}
            disabled={!flowName.trim() || creating}
            className="w-full"
          >
            {creating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Creating...
              </>
            ) : (
              "Create Flow"
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 14: Main Flow Canvas Component

**Files:**
- Create: `frontend/src/components/flow/FlowCanvas.tsx`

- [ ] **Step 1: Create the main canvas component that composes everything**

```tsx
// frontend/src/components/flow/FlowCanvas.tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  type OnConnect,
  BackgroundVariant,
  Panel,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { toast } from "sonner";
import { Loader2 } from "lucide-react";

import type {
  FlowDefinition,
  FlowVersion,
  FlowNodeData,
  FlowEdgeData,
  FlowNodeType,
  ValidationResult,
} from "@/lib/flow-types";
import { getDefaultConfig, NODE_TYPE_REGISTRY } from "@/lib/flow-types";
import { applyDagreLayout } from "@/lib/flow-layout";
import { validateFlowGraph } from "@/lib/flow-validation";
import { useFlowHistory } from "@/hooks/use-flow-history";
import * as flowsApi from "@/lib/flows-api";

import { NodePalette } from "./NodePalette";
import { PropertiesPanel } from "./PropertiesPanel";
import { CanvasToolbar } from "./CanvasToolbar";
import { ValidationPanel } from "./ValidationPanel";

import { VoiceCallNode } from "./nodes/VoiceCallNode";
import { WhatsAppTemplateNode } from "./nodes/WhatsAppTemplateNode";
import { WhatsAppSessionNode } from "./nodes/WhatsAppSessionNode";
import { AIGenerateNode } from "./nodes/AIGenerateNode";
import { ConditionNode } from "./nodes/ConditionNode";
import { DelayWaitNode } from "./nodes/DelayWaitNode";
import { WaitForEventNode } from "./nodes/WaitForEventNode";
import { GoalMetNode } from "./nodes/GoalMetNode";
import { EndNode } from "./nodes/EndNode";

// ---------------------------------------------------------------------------
// Node type registry for React Flow
// ---------------------------------------------------------------------------
const nodeTypes: NodeTypes = {
  voice_call: VoiceCallNode,
  whatsapp_template: WhatsAppTemplateNode,
  whatsapp_session: WhatsAppSessionNode,
  ai_generate_send: AIGenerateNode,
  condition: ConditionNode,
  delay_wait: DelayWaitNode,
  wait_for_event: WaitForEventNode,
  goal_met: GoalMetNode,
  end: EndNode,
};

// ---------------------------------------------------------------------------
// Helpers: convert between API data and React Flow format
// ---------------------------------------------------------------------------
function apiNodesToRF(apiNodes: FlowNodeData[]): Node[] {
  return apiNodes.map((n) => ({
    id: n.id,
    type: n.node_type,
    position: { x: n.position_x, y: n.position_y },
    data: {
      label: n.name,
      nodeType: n.node_type,
      config: n.config,
    },
  }));
}

function apiEdgesToRF(apiEdges: FlowEdgeData[]): Edge[] {
  return apiEdges.map((e) => ({
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: e.condition_label,
    label: e.condition_label,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { strokeWidth: 2 },
    labelStyle: { fontSize: 11, fontWeight: 500 },
  }));
}

function rfNodesToAPI(rfNodes: Node[], versionId: string): FlowNodeData[] {
  return rfNodes.map((n) => ({
    id: n.id,
    version_id: versionId,
    node_type: (n.data.nodeType || n.type) as FlowNodeType,
    name: (n.data.label as string) || "",
    position_x: n.position.x,
    position_y: n.position.y,
    config: (n.data.config as Record<string, any>) || {},
    created_at: "",
  }));
}

function rfEdgesToAPI(rfEdges: Edge[], versionId: string): FlowEdgeData[] {
  return rfEdges.map((e, i) => ({
    id: e.id,
    version_id: versionId,
    source_node_id: e.source,
    target_node_id: e.target,
    condition_label: (e.sourceHandle as string) || (e.label as string) || "default",
    sort_order: i,
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface FlowCanvasProps {
  flowId: string;
  flow: FlowDefinition;
  version: FlowVersion;
  bots: Array<{ id: string; name: string }>;
  onPublished: () => void;
}

export function FlowCanvas({ flowId, flow, version, bots, onPublished }: FlowCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(apiNodesToRF(version.nodes));
  const [edges, setEdges, onEdgesChange] = useEdgesState(apiEdgesToRF(version.edges));
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const history = useFlowHistory();
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const isDraft = version.status === "draft";

  // -----------------------------------------------------------------------
  // Auto-save with debounce
  // -----------------------------------------------------------------------
  const scheduleSave = useCallback(() => {
    if (!isDraft) return;
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      setIsSaving(true);
      try {
        await flowsApi.saveGraph(flowId, version.id, {
          nodes: rfNodesToAPI(nodes, version.id),
          edges: rfEdgesToAPI(edges, version.id),
        });
      } catch {
        toast.error("Failed to save flow");
      } finally {
        setIsSaving(false);
      }
    }, 1500);
  }, [flowId, version.id, version.status, isDraft, nodes, edges]);

  // Trigger save when nodes/edges change (but not on initial load)
  const isInitialLoad = useRef(true);
  useEffect(() => {
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      return;
    }
    scheduleSave();
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [nodes, edges, scheduleSave]);

  // -----------------------------------------------------------------------
  // Connection handler
  // -----------------------------------------------------------------------
  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      history.pushState(nodes, edges, "Connect edge");
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            label: params.sourceHandle || "default",
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { strokeWidth: 2 },
            labelStyle: { fontSize: 11, fontWeight: 500 },
          },
          eds,
        ),
      );
    },
    [nodes, edges, history, setEdges],
  );

  // -----------------------------------------------------------------------
  // Drop handler — add nodes from palette
  // -----------------------------------------------------------------------
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (!isDraft) return;

      const nodeType = event.dataTransfer.getData("application/reactflow-nodetype") as FlowNodeType;
      if (!nodeType) return;

      const info = NODE_TYPE_REGISTRY.find((n) => n.type === nodeType);
      if (!info) return;

      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!reactFlowBounds) return;

      const position = {
        x: event.clientX - reactFlowBounds.left - 110,
        y: event.clientY - reactFlowBounds.top - 40,
      };

      history.pushState(nodes, edges, `Add ${info.label}`);

      const newNode: Node = {
        id: `temp_${Date.now()}`,
        type: nodeType,
        position,
        data: {
          label: info.label,
          nodeType,
          config: getDefaultConfig(nodeType),
        },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [isDraft, nodes, edges, history, setNodes],
  );

  // -----------------------------------------------------------------------
  // Node selection
  // -----------------------------------------------------------------------
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // -----------------------------------------------------------------------
  // Update node from properties panel
  // -----------------------------------------------------------------------
  const handleUpdateNode = useCallback(
    (nodeId: string, updates: Partial<Node["data"]>) => {
      history.pushState(nodes, edges, "Update node config");
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n,
        ),
      );
      // Update selectedNode reference
      setSelectedNode((prev) =>
        prev && prev.id === nodeId ? { ...prev, data: { ...prev.data, ...updates } } : prev,
      );
    },
    [nodes, edges, history, setNodes],
  );

  // -----------------------------------------------------------------------
  // Delete selected nodes/edges
  // -----------------------------------------------------------------------
  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      history.pushState(nodes, edges, `Delete ${deleted.length} node(s)`);
    },
    [nodes, edges, history],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      history.pushState(nodes, edges, `Delete ${deleted.length} edge(s)`);
    },
    [nodes, edges, history],
  );

  // -----------------------------------------------------------------------
  // Undo / Redo
  // -----------------------------------------------------------------------
  const handleUndo = useCallback(() => {
    const entry = history.undo(nodes, edges);
    if (entry) {
      setNodes(entry.nodes);
      setEdges(entry.edges);
    }
  }, [nodes, edges, history, setNodes, setEdges]);

  const handleRedo = useCallback(() => {
    const entry = history.redo(nodes, edges);
    if (entry) {
      setNodes(entry.nodes);
      setEdges(entry.edges);
    }
  }, [nodes, edges, history, setNodes, setEdges]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if (mod && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleUndo, handleRedo]);

  // -----------------------------------------------------------------------
  // Auto-layout
  // -----------------------------------------------------------------------
  const handleAutoLayout = useCallback(() => {
    history.pushState(nodes, edges, "Auto layout");
    const layouted = applyDagreLayout(nodes, edges);
    setNodes(layouted);
  }, [nodes, edges, history, setNodes]);

  // -----------------------------------------------------------------------
  // Validate
  // -----------------------------------------------------------------------
  const handleValidate = useCallback(async () => {
    setIsValidating(true);
    try {
      // Client-side first for instant feedback
      const clientResult = validateFlowGraph(nodes, edges);
      setValidationResult(clientResult);

      // Then server-side for authoritative result
      const serverResult = await flowsApi.validateFlow(flowId, version.id);
      setValidationResult(serverResult);
    } catch {
      toast.error("Validation failed");
    } finally {
      setIsValidating(false);
    }
  }, [nodes, edges, flowId, version.id]);

  // -----------------------------------------------------------------------
  // Publish
  // -----------------------------------------------------------------------
  const handlePublish = useCallback(async () => {
    setIsPublishing(true);
    try {
      // Save first
      await flowsApi.saveGraph(flowId, version.id, {
        nodes: rfNodesToAPI(nodes, version.id),
        edges: rfEdgesToAPI(edges, version.id),
      });

      // Then validate
      const result = await flowsApi.validateFlow(flowId, version.id);
      if (!result.valid) {
        setValidationResult(result);
        toast.error(`Cannot publish: ${result.errors.length} validation error(s)`);
        return;
      }

      // Publish
      await flowsApi.publishVersion(flowId, version.id);
      toast.success("Flow published successfully!");
      onPublished();
    } catch (err: any) {
      toast.error(err.message || "Failed to publish flow");
    } finally {
      setIsPublishing(false);
    }
  }, [flowId, version.id, nodes, edges, onPublished]);

  // -----------------------------------------------------------------------
  // Simulate (placeholder — opens simulation route)
  // -----------------------------------------------------------------------
  const handleSimulate = useCallback(() => {
    toast.info("Simulation is not yet implemented");
  }, []);

  // -----------------------------------------------------------------------
  // Focus node from validation panel
  // -----------------------------------------------------------------------
  const handleFocusNode = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      if (node) {
        setSelectedNode(node);
      }
    },
    [nodes],
  );

  return (
    <div className="flex h-full">
      {/* Left: Node Palette */}
      {isDraft && <NodePalette />}

      {/* Center: Canvas */}
      <div className="relative flex-1" ref={reactFlowWrapper}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={isDraft ? onNodesChange : undefined}
          onEdgesChange={isDraft ? onEdgesChange : undefined}
          onConnect={isDraft ? onConnect : undefined}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onDragOver={onDragOver}
          onDrop={onDrop}
          onNodesDelete={onNodesDelete}
          onEdgesDelete={onEdgesDelete}
          nodeTypes={nodeTypes}
          fitView
          snapToGrid
          snapGrid={[20, 20]}
          deleteKeyCode={isDraft ? ["Backspace", "Delete"] : null}
          className="bg-muted/30"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls position="bottom-left" />
          <MiniMap
            position="bottom-right"
            nodeColor={(n) => {
              const info = NODE_TYPE_REGISTRY.find((r) => r.type === n.type);
              return info ? info.color.replace("border-", "").replace("-500", "") : "#888";
            }}
            maskColor="rgba(0,0,0,0.1)"
          />

          {/* Toolbar */}
          <Panel position="top-center">
            <CanvasToolbar
              canUndo={history.canUndo}
              canRedo={history.canRedo}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onAutoLayout={handleAutoLayout}
              onValidate={handleValidate}
              onPublish={handlePublish}
              onSimulate={handleSimulate}
              isPublishing={isPublishing}
              isValidating={isValidating}
              isDraft={isDraft}
            />
          </Panel>

          {/* Save indicator */}
          {isSaving && (
            <Panel position="top-right">
              <div className="flex items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Saving...
              </div>
            </Panel>
          )}
        </ReactFlow>

        {/* Validation results */}
        <ValidationPanel
          result={validationResult}
          onClose={() => setValidationResult(null)}
          onFocusNode={handleFocusNode}
        />
      </div>

      {/* Right: Properties Panel */}
      {selectedNode && (
        <PropertiesPanel
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdateNode={handleUpdateNode}
          bots={bots}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 15: Flow Canvas Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/[id]/flow/page.tsx`

- [ ] **Step 1: Create the flow canvas page — loads flow data and renders FlowCanvas**

```tsx
// frontend/src/app/(app)/sequences/[id]/flow/page.tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { ArrowLeft, Loader2, Workflow } from "lucide-react";
import { toast } from "sonner";

import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import type { FlowDefinition, FlowVersion } from "@/lib/flow-types";
import { fetchFlow, createDraftVersion } from "@/lib/flows-api";
import { fetchBots } from "@/lib/api";
import { FlowCanvas } from "@/components/flow/FlowCanvas";

export default function FlowCanvasPage() {
  const router = useRouter();
  const params = useParams();
  const flowId = params.id as string;

  const [flow, setFlow] = useState<FlowDefinition | null>(null);
  const [version, setVersion] = useState<FlowVersion | null>(null);
  const [bots, setBots] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);

  const loadFlow = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchFlow(flowId);
      setFlow(data);

      // Use draft version if available, otherwise published
      const activeVersion = data.draft_version || data.published_version;
      if (!activeVersion) {
        toast.error("No version found for this flow");
        router.push("/sequences");
        return;
      }
      setVersion(activeVersion);
    } catch {
      toast.error("Failed to load flow");
      router.push("/sequences");
    } finally {
      setLoading(false);
    }
  }, [flowId, router]);

  const loadBots = useCallback(async () => {
    try {
      const data = await fetchBots();
      setBots(data.map((b) => ({ id: b.id, name: b.agent_name || b.company_name || "Unnamed" })));
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    loadFlow();
    loadBots();
  }, [loadFlow, loadBots]);

  const handleEditDraft = useCallback(async () => {
    if (!flow) return;
    try {
      const newDraft = await createDraftVersion(flowId);
      setVersion(newDraft);
      toast.success("Draft version created — you can now edit the flow");
    } catch (err: any) {
      toast.error(err.message || "Failed to create draft");
    }
  }, [flow, flowId]);

  const handlePublished = useCallback(() => {
    loadFlow(); // Reload to get updated version status
  }, [loadFlow]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!flow || !version) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <Workflow className="h-12 w-12 text-muted-foreground opacity-30" />
        <p className="text-muted-foreground">Flow not found</p>
        <Button variant="outline" onClick={() => router.push("/sequences")}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Flows
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <Header>
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.push("/sequences")} className="h-8 gap-1.5">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">{flow.name}</h1>
            <Badge variant={version.status === "draft" ? "secondary" : version.status === "published" ? "default" : "outline"}>
              {version.status} v{version.version_number}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {version.status === "published" && (
            <Button size="sm" variant="outline" onClick={handleEditDraft}>
              Edit as Draft
            </Button>
          )}
        </div>
      </Header>

      {/* Canvas — fills remaining space */}
      <div className="flex-1 overflow-hidden">
        <FlowCanvas
          flowId={flowId}
          flow={flow}
          version={version}
          bots={bots}
          onPublished={handlePublished}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 16: Adapt Sequences List Page for Flows

**Files:**
- Modify: `frontend/src/app/(app)/sequences/page.tsx`

- [ ] **Step 1: Add a "Flows" section to the existing sequences page**

At the top of the component (after existing state declarations), add flow-related state and fetch logic. The page should show two sections: "Flows" (new) and "Legacy Templates" (existing).

Add these imports at the top of the file:

```typescript
import { fetchFlows, createFlow, deleteFlow, type FlowDefinition } from "@/lib/flows-api";
import { TemplatePicker } from "@/components/flow/TemplatePicker";
```

Add new state after the existing state declarations:

```typescript
  // Flow state
  const [flows, setFlows] = useState<FlowDefinition[]>([]);
  const [flowsTotal, setFlowsTotal] = useState(0);
  const [flowsLoading, setFlowsLoading] = useState(true);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
```

Add a `loadFlows` function:

```typescript
  const loadFlows = useCallback(async () => {
    setFlowsLoading(true);
    try {
      const data = await fetchFlows();
      setFlows(data.flows);
      setFlowsTotal(data.total);
    } catch {
      // Flows API not yet available — silently skip
    } finally {
      setFlowsLoading(false);
    }
  }, []);
```

Call `loadFlows()` in the existing `useEffect`.

Add the create flow handler:

```typescript
  const handleCreateFlow = async (name: string, templateId: string) => {
    const newFlow = await createFlow({ name, template_id: templateId, trigger_type: "post_call" });
    router.push(`/sequences/${newFlow.id}/flow`);
  };
```

Add a "Flows" section above the existing templates table:

```tsx
  {/* Flow Builder section */}
  <div className="mb-8">
    <div className="mb-4 flex items-center justify-between">
      <h2 className="text-lg font-semibold">Flow Builder</h2>
      <Button size="sm" onClick={() => setTemplatePickerOpen(true)}>
        <Plus className="mr-1.5 h-4 w-4" />
        New Flow
      </Button>
    </div>
    {flowsLoading ? (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    ) : flows.length === 0 ? (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <Workflow className="mb-2 h-8 w-8 opacity-30" />
          <p className="text-sm">No flows yet. Create your first flow to get started.</p>
        </CardContent>
      </Card>
    ) : (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Trigger</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Active</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {flows.map((flow) => (
            <TableRow
              key={flow.id}
              className="cursor-pointer"
              onClick={() => router.push(`/sequences/${flow.id}/flow`)}
            >
              <TableCell className="font-medium">{flow.name}</TableCell>
              <TableCell>{triggerLabel(flow.trigger_type)}</TableCell>
              <TableCell>
                <Badge variant={flow.published_version ? "default" : "secondary"}>
                  {flow.published_version ? "Published" : "Draft"}
                </Badge>
              </TableCell>
              <TableCell>
                <Switch
                  checked={flow.is_active}
                  onClick={(e) => e.stopPropagation()}
                  disabled
                />
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-destructive"
                  onClick={(e) => {
                    e.stopPropagation();
                    // TODO: wire up delete confirmation
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    )}
  </div>

  {/* Template Picker Dialog */}
  <TemplatePicker
    open={templatePickerOpen}
    onOpenChange={setTemplatePickerOpen}
    onCreate={handleCreateFlow}
  />
```

- [ ] **Step 2: Update NAV_LINKS to include "Flows" as the primary tab**

```typescript
const NAV_LINKS = [
  { href: "/sequences", label: "Flows" },
  { href: "/sequences/monitor", label: "Monitor" },
  { href: "/sequences/analytics", label: "Analytics" },
];
```

- [ ] **Step 3: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Install `@xyflow/react` + `@dagrejs/dagre` | `package.json` |
| 2 | TypeScript types + API client | `flow-types.ts`, `flows-api.ts` |
| 3 | Auto-layout with dagre | `flow-layout.ts` |
| 4 | Undo/redo hook | `use-flow-history.ts` |
| 5 | Client-side validation | `flow-validation.ts` |
| 6 | Flow templates | `flow-templates.ts` |
| 7 | Base node component | `BaseNode.tsx` |
| 8 | 9 custom node components | `VoiceCallNode.tsx`, etc. |
| 9 | Node palette (left sidebar) | `NodePalette.tsx` |
| 10 | Properties panel (right sidebar) | `PropertiesPanel.tsx` |
| 11 | Canvas toolbar | `CanvasToolbar.tsx` |
| 12 | Validation panel | `ValidationPanel.tsx` |
| 13 | Template picker dialog | `TemplatePicker.tsx` |
| 14 | Main FlowCanvas component | `FlowCanvas.tsx` |
| 15 | Flow canvas page | `[id]/flow/page.tsx` |
| 16 | Adapt sequences list page | `sequences/page.tsx` |

**Estimated effort:** 2-3 days for an experienced frontend developer, or 1 day for an agentic worker executing task-by-task.

**Verification checklist:**
- `npx tsc --noEmit` passes after each task
- Canvas renders with drag-and-drop from palette
- Undo/redo works with Ctrl+Z / Ctrl+Y
- Auto-layout produces clean top-down graph
- Validation shows errors inline
- Publish flow triggers server validation
- Properties panel updates node config in real-time
- Save indicator shows during autosave
