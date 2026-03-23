# Flow Builder Plan 5: Simulation & Testing

**Spec reference:** §8.1 Visual Dry-Run, §8.2 Live Test Mode, §8.3 Journey Replay, §10.3 Canvas Leads Panel, §12 Simulation endpoints

**Depends on:** Plan 2 (Data Model), Plan 3 (Canvas UI), Plan 4 (Flow Engine)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `frontend/src/lib/flow-simulation.ts` | Client-side dry-run engine (graph walker) |
| Create | `frontend/src/lib/flows-api.ts` | Flow API client (simulation, live test, journey) |
| Create | `frontend/src/components/flow/SimulationToolbar.tsx` | Simulation controls overlay |
| Create | `frontend/src/components/flow/MockLeadDialog.tsx` | Mock lead profile picker/editor |
| Create | `frontend/src/components/flow/OutcomePickerPopover.tsx` | Branch outcome selector at condition nodes |
| Create | `frontend/src/components/flow/SimulationSummary.tsx` | Journey summary at End/Goal node |
| Create | `frontend/src/components/flow/LiveTestDialog.tsx` | Phone number input + delay config |
| Create | `frontend/src/components/flow/LeadsPanel.tsx` | Sidebar drawer with leads in flow |
| Create | `frontend/src/components/flow/JourneyOverlay.tsx` | Path highlighting overlay for replay |
| Create | `frontend/src/hooks/use-flow-simulation.ts` | Simulation state machine hook |
| Create | `frontend/src/hooks/use-flow-journey.ts` | Journey replay data fetching hook |
| Create | `app/api/flow_simulation.py` | Backend: simulate + live-test endpoints |
| Create | `tests/test_flow_simulation.py` | Backend simulation tests |
| Create | `frontend/src/components/flow/__tests__/simulation.test.tsx` | Frontend simulation tests |

---

## Task 1: Client-Side Dry-Run Engine

**Files:**
- Create: `frontend/src/lib/flow-simulation.ts`
- Create: `frontend/src/lib/flow-simulation.test.ts`

- [ ] **Step 1: Write failing tests for the graph walker**

```typescript
// frontend/src/lib/__tests__/flow-simulation.test.ts
import { describe, it, expect } from "vitest";
import {
  SimulationEngine,
  type SimulationState,
  type MockLead,
  type FlowGraph,
} from "../flow-simulation";

const MOCK_LEAD: MockLead = {
  name: "Test Lead",
  phone: "+919876543210",
  interest_level: 8,
  sentiment: "positive",
  goal_outcome: "callback",
};

// Simple linear flow: Trigger → VoiceCall → End
function buildLinearGraph(): FlowGraph {
  return {
    nodes: [
      { id: "n1", type: "voice_call", name: "Welcome Call", config: { bot_id: "bot-1", max_duration: 300 }, position: { x: 0, y: 0 } },
      { id: "n2", type: "end", name: "Done", config: {}, position: { x: 0, y: 200 } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2", condition_label: "default" },
    ],
    entryNodeId: "n1",
  };
}

// Branching flow: VoiceCall → Condition(interest_level >= 7) → [yes: WhatsApp, no: End]
function buildBranchingGraph(): FlowGraph {
  return {
    nodes: [
      { id: "n1", type: "voice_call", name: "Intro Call", config: { bot_id: "bot-1" }, position: { x: 0, y: 0 } },
      {
        id: "n2", type: "condition", name: "Check Interest", config: {
          conditions: [
            { label: "interested", rules: [{ field: "interest_level", operator: "gte", value: 7 }] },
          ],
          default_label: "not_interested",
        }, position: { x: 0, y: 200 },
      },
      { id: "n3", type: "whatsapp_template", name: "Follow-up", config: { template_name: "follow_up" }, position: { x: -100, y: 400 } },
      { id: "n4", type: "end", name: "Drop Off", config: {}, position: { x: 100, y: 400 } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2", condition_label: "default" },
      { id: "e2", source: "n2", target: "n3", condition_label: "interested" },
      { id: "e3", source: "n2", target: "n4", condition_label: "not_interested" },
    ],
    entryNodeId: "n1",
  };
}

describe("SimulationEngine", () => {
  it("initializes at entry node", () => {
    const engine = new SimulationEngine(buildLinearGraph(), MOCK_LEAD);
    const state = engine.getState();
    expect(state.currentNodeId).toBe("n1");
    expect(state.visitedNodeIds).toEqual(["n1"]);
    expect(state.visitedEdgeIds).toEqual([]);
    expect(state.status).toBe("active");
  });

  it("advances through linear flow to end", () => {
    const engine = new SimulationEngine(buildLinearGraph(), MOCK_LEAD);

    // At voice_call node — advance with default outcome
    const step1 = engine.advance("default");
    expect(step1.currentNodeId).toBe("n2");
    expect(step1.visitedNodeIds).toEqual(["n1", "n2"]);
    expect(step1.visitedEdgeIds).toEqual(["e1"]);
    expect(step1.status).toBe("completed");
  });

  it("auto-evaluates condition nodes from mock lead data", () => {
    const engine = new SimulationEngine(buildBranchingGraph(), MOCK_LEAD);

    // Advance past voice_call
    engine.advance("default");
    // Now at condition node — auto-evaluate
    const result = engine.autoEvaluate();
    expect(result.resolvedLabel).toBe("interested");
    expect(result.currentNodeId).toBe("n3");
  });

  it("allows manual outcome pick at condition nodes", () => {
    const lowInterestLead = { ...MOCK_LEAD, interest_level: 3 };
    const engine = new SimulationEngine(buildBranchingGraph(), lowInterestLead);

    engine.advance("default");
    // Override auto-evaluation, manually pick "interested"
    const result = engine.advance("interested");
    expect(result.currentNodeId).toBe("n3");
  });

  it("generates action preview at action nodes", () => {
    const engine = new SimulationEngine(buildLinearGraph(), MOCK_LEAD);
    const preview = engine.getActionPreview();
    expect(preview).toEqual({
      nodeType: "voice_call",
      nodeName: "Welcome Call",
      description: "Voice call using bot bot-1 (max 300s)",
      config: { bot_id: "bot-1", max_duration: 300 },
    });
  });

  it("builds journey summary at end node", () => {
    const engine = new SimulationEngine(buildLinearGraph(), MOCK_LEAD);
    engine.advance("default");
    const summary = engine.getJourneySummary();
    expect(summary.totalSteps).toBe(2);
    expect(summary.path).toHaveLength(2);
    expect(summary.path[0].nodeId).toBe("n1");
    expect(summary.path[1].nodeId).toBe("n2");
    expect(summary.endReason).toBe("reached_end");
  });

  it("reports goals hit", () => {
    const graphWithGoal: FlowGraph = {
      nodes: [
        { id: "n1", type: "voice_call", name: "Call", config: {}, position: { x: 0, y: 0 } },
        { id: "n2", type: "goal_met", name: "Booked!", config: { goal_name: "meeting_booked" }, position: { x: 0, y: 200 } },
      ],
      edges: [
        { id: "e1", source: "n1", target: "n2", condition_label: "default" },
      ],
      entryNodeId: "n1",
    };
    const engine = new SimulationEngine(graphWithGoal, MOCK_LEAD);
    engine.advance("default");
    const summary = engine.getJourneySummary();
    expect(summary.goalsHit).toEqual(["meeting_booked"]);
    expect(summary.endReason).toBe("goal_met");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/__tests__/flow-simulation.test.ts`
Expected: FAIL — module `../flow-simulation` does not exist

- [ ] **Step 3: Implement the simulation engine**

```typescript
// frontend/src/lib/flow-simulation.ts

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MockLead {
  name: string;
  phone: string;
  interest_level?: number;
  sentiment?: string;
  goal_outcome?: string;
  [key: string]: any;
}

export interface FlowGraphNode {
  id: string;
  type: string;
  name: string;
  config: Record<string, any>;
  position: { x: number; y: number };
}

export interface FlowGraphEdge {
  id: string;
  source: string;
  target: string;
  condition_label: string;
}

export interface FlowGraph {
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
  entryNodeId: string;
}

export interface ActionPreview {
  nodeType: string;
  nodeName: string;
  description: string;
  config: Record<string, any>;
}

export interface JourneyStep {
  nodeId: string;
  nodeType: string;
  nodeName: string;
  outcome?: string;
}

export interface JourneySummary {
  totalSteps: number;
  path: JourneyStep[];
  goalsHit: string[];
  endReason: "reached_end" | "goal_met" | "no_outgoing_edge" | "active";
}

export interface SimulationState {
  currentNodeId: string;
  visitedNodeIds: string[];
  visitedEdgeIds: string[];
  status: "active" | "completed";
  resolvedLabel?: string;
}

// ---------------------------------------------------------------------------
// Condition evaluator
// ---------------------------------------------------------------------------

type Operator = "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "regex";

function evaluateRule(
  lead: MockLead,
  rule: { field: string; operator: Operator; value: any },
): boolean {
  const fieldValue = lead[rule.field];
  switch (rule.operator) {
    case "eq":
      return fieldValue === rule.value;
    case "neq":
      return fieldValue !== rule.value;
    case "gt":
      return typeof fieldValue === "number" && fieldValue > rule.value;
    case "gte":
      return typeof fieldValue === "number" && fieldValue >= rule.value;
    case "lt":
      return typeof fieldValue === "number" && fieldValue < rule.value;
    case "lte":
      return typeof fieldValue === "number" && fieldValue <= rule.value;
    case "contains":
      return typeof fieldValue === "string" && fieldValue.includes(rule.value);
    case "regex":
      return typeof fieldValue === "string" && new RegExp(rule.value).test(fieldValue);
    default:
      return false;
  }
}

function evaluateConditionNode(
  config: Record<string, any>,
  lead: MockLead,
): string {
  const conditions = config.conditions || [];
  for (const condition of conditions) {
    const allMatch = (condition.rules || []).every((rule: any) =>
      evaluateRule(lead, rule),
    );
    if (allMatch) return condition.label;
  }
  return config.default_label || "default";
}

// ---------------------------------------------------------------------------
// Action preview generator
// ---------------------------------------------------------------------------

function generateActionDescription(node: FlowGraphNode): string {
  switch (node.type) {
    case "voice_call": {
      const parts = [`Voice call using bot ${node.config.bot_id || "default"}`];
      if (node.config.max_duration) parts[0] += ` (max ${node.config.max_duration}s)`;
      return parts[0];
    }
    case "whatsapp_template":
      return `WhatsApp template: ${node.config.template_name || "unknown"}`;
    case "whatsapp_session":
      return `WhatsApp session message${node.config.ai_prompt ? " (AI-generated)" : ""}`;
    case "ai_generate_send":
      return `AI-generated ${node.config.channel || "message"} using ${node.config.model || "default model"}`;
    case "delay_wait":
      return `Wait ${node.config.duration || "?"} ${node.config.unit || "hours"}`;
    case "wait_for_event":
      return `Wait for event: ${node.config.event_type || "unknown"} (timeout: ${node.config.timeout_hours || "?"}h)`;
    case "goal_met":
      return `Goal reached: ${node.config.goal_name || "unnamed"}`;
    case "end":
      return "End of flow";
    case "condition":
      return `Evaluate conditions (${(node.config.conditions || []).length} branches)`;
    default:
      return `${node.type} node`;
  }
}

// ---------------------------------------------------------------------------
// Simulation Engine
// ---------------------------------------------------------------------------

export class SimulationEngine {
  private graph: FlowGraph;
  private lead: MockLead;
  private currentNodeId: string;
  private visitedNodeIds: string[];
  private visitedEdgeIds: string[];
  private outcomes: JourneyStep[];

  constructor(graph: FlowGraph, lead: MockLead) {
    this.graph = graph;
    this.lead = lead;
    this.currentNodeId = graph.entryNodeId;
    this.visitedNodeIds = [graph.entryNodeId];
    this.visitedEdgeIds = [];
    this.outcomes = [this.buildStep(graph.entryNodeId)];
  }

  private getNode(id: string): FlowGraphNode {
    const node = this.graph.nodes.find((n) => n.id === id);
    if (!node) throw new Error(`Node ${id} not found`);
    return node;
  }

  private getOutgoingEdges(nodeId: string): FlowGraphEdge[] {
    return this.graph.edges.filter((e) => e.source === nodeId);
  }

  private isTerminal(nodeId: string): boolean {
    const node = this.getNode(nodeId);
    return node.type === "end" || node.type === "goal_met";
  }

  private buildStep(nodeId: string, outcome?: string): JourneyStep {
    const node = this.getNode(nodeId);
    return { nodeId, nodeType: node.type, nodeName: node.name, outcome };
  }

  getState(): SimulationState {
    return {
      currentNodeId: this.currentNodeId,
      visitedNodeIds: [...this.visitedNodeIds],
      visitedEdgeIds: [...this.visitedEdgeIds],
      status: this.isTerminal(this.currentNodeId) ? "completed" : "active",
    };
  }

  /**
   * Advance to the next node using the given outcome/condition label.
   * For action nodes, use "default". For condition nodes, use the condition label.
   */
  advance(outcomeLabel: string): SimulationState {
    if (this.isTerminal(this.currentNodeId)) {
      return this.getState();
    }

    const edges = this.getOutgoingEdges(this.currentNodeId);
    const edge = edges.find((e) => e.condition_label === outcomeLabel)
      || edges.find((e) => e.condition_label === "default");

    if (!edge) {
      // No matching edge — stay at current node
      return this.getState();
    }

    // Record the outcome on the current step
    this.outcomes[this.outcomes.length - 1].outcome = outcomeLabel;

    // Move to target
    this.currentNodeId = edge.target;
    this.visitedNodeIds.push(edge.target);
    this.visitedEdgeIds.push(edge.id);
    this.outcomes.push(this.buildStep(edge.target));

    // If the new node is a condition, don't auto-advance — let the user pick or auto-evaluate
    return this.getState();
  }

  /**
   * Auto-evaluate the current condition node using mock lead data.
   * Returns the state after advancing, plus the resolved label.
   */
  autoEvaluate(): SimulationState & { resolvedLabel: string } {
    const node = this.getNode(this.currentNodeId);
    if (node.type !== "condition") {
      throw new Error(`Cannot auto-evaluate non-condition node: ${node.type}`);
    }

    const resolvedLabel = evaluateConditionNode(node.config, this.lead);
    const state = this.advance(resolvedLabel);
    return { ...state, resolvedLabel };
  }

  /**
   * Get a human-readable preview of what the current action node would do.
   */
  getActionPreview(): ActionPreview {
    const node = this.getNode(this.currentNodeId);
    return {
      nodeType: node.type,
      nodeName: node.name,
      description: generateActionDescription(node),
      config: node.config,
    };
  }

  /**
   * Get a summary of the simulated journey so far.
   */
  getJourneySummary(): JourneySummary {
    const currentNode = this.getNode(this.currentNodeId);
    let endReason: JourneySummary["endReason"] = "active";
    if (currentNode.type === "goal_met") endReason = "goal_met";
    else if (currentNode.type === "end") endReason = "reached_end";

    const goalsHit = this.outcomes
      .filter((s) => s.nodeType === "goal_met")
      .map((s) => {
        const node = this.getNode(s.nodeId);
        return node.config.goal_name || s.nodeName;
      });

    return {
      totalSteps: this.outcomes.length,
      path: [...this.outcomes],
      goalsHit,
      endReason,
    };
  }

  /**
   * Reset to the beginning.
   */
  reset(): void {
    this.currentNodeId = this.graph.entryNodeId;
    this.visitedNodeIds = [this.graph.entryNodeId];
    this.visitedEdgeIds = [];
    this.outcomes = [this.buildStep(this.graph.entryNodeId)];
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/__tests__/flow-simulation.test.ts`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/flow-simulation.ts frontend/src/lib/__tests__/flow-simulation.test.ts
git commit -m "feat: add client-side flow simulation engine with condition evaluation

Pure TypeScript graph walker for visual dry-run mode. Supports linear
advancement, auto-evaluation of condition nodes from mock lead data,
manual outcome picking, action previews, and journey summaries."
```

---

## Task 2: Simulation State Hook + Toolbar

**Files:**
- Create: `frontend/src/hooks/use-flow-simulation.ts`
- Create: `frontend/src/components/flow/SimulationToolbar.tsx`
- Create: `frontend/src/components/flow/MockLeadDialog.tsx`
- Create: `frontend/src/components/flow/OutcomePickerPopover.tsx`
- Create: `frontend/src/components/flow/SimulationSummary.tsx`

- [ ] **Step 1: Write failing test for the simulation hook**

```typescript
// frontend/src/hooks/__tests__/use-flow-simulation.test.ts
import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useFlowSimulation } from "../use-flow-simulation";
import type { FlowGraph, MockLead } from "@/lib/flow-simulation";

const MOCK_LEAD: MockLead = {
  name: "Test Lead",
  phone: "+919876543210",
  interest_level: 8,
};

const SIMPLE_GRAPH: FlowGraph = {
  nodes: [
    { id: "n1", type: "voice_call", name: "Call", config: {}, position: { x: 0, y: 0 } },
    { id: "n2", type: "end", name: "End", config: {}, position: { x: 0, y: 200 } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2", condition_label: "default" },
  ],
  entryNodeId: "n1",
};

describe("useFlowSimulation", () => {
  it("starts inactive", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    expect(result.current.isActive).toBe(false);
    expect(result.current.simulationState).toBeNull();
  });

  it("starts simulation with mock lead", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    expect(result.current.isActive).toBe(true);
    expect(result.current.simulationState?.currentNodeId).toBe("n1");
  });

  it("advances to next node", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.next("default"));
    expect(result.current.simulationState?.currentNodeId).toBe("n2");
    expect(result.current.simulationState?.status).toBe("completed");
  });

  it("provides action preview", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    expect(result.current.actionPreview?.nodeType).toBe("voice_call");
  });

  it("resets simulation", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.next("default"));
    act(() => result.current.reset());
    expect(result.current.simulationState?.currentNodeId).toBe("n1");
  });

  it("stops simulation", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.stop());
    expect(result.current.isActive).toBe(false);
    expect(result.current.simulationState).toBeNull();
  });

  it("auto-plays through flow with delays", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.autoPlay(500)); // 500ms between steps

    await act(async () => { vi.advanceTimersByTime(600); });
    expect(result.current.simulationState?.currentNodeId).toBe("n2");
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/use-flow-simulation.test.ts`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement `useFlowSimulation` hook**

```typescript
// frontend/src/hooks/use-flow-simulation.ts
"use client";

import { useState, useCallback, useRef } from "react";
import {
  SimulationEngine,
  type FlowGraph,
  type MockLead,
  type SimulationState,
  type ActionPreview,
  type JourneySummary,
} from "@/lib/flow-simulation";

export interface UseFlowSimulationReturn {
  isActive: boolean;
  simulationState: SimulationState | null;
  actionPreview: ActionPreview | null;
  journeySummary: JourneySummary | null;
  start: (lead: MockLead) => void;
  stop: () => void;
  next: (outcomeLabel: string) => void;
  autoEvaluate: () => { resolvedLabel: string } | null;
  autoPlay: (intervalMs?: number) => void;
  stopAutoPlay: () => void;
  reset: () => void;
}

export function useFlowSimulation(graph: FlowGraph): UseFlowSimulationReturn {
  const [isActive, setIsActive] = useState(false);
  const [simulationState, setSimulationState] = useState<SimulationState | null>(null);
  const [actionPreview, setActionPreview] = useState<ActionPreview | null>(null);
  const [journeySummary, setJourneySummary] = useState<JourneySummary | null>(null);
  const engineRef = useRef<SimulationEngine | null>(null);
  const autoPlayRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const updateState = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const state = engine.getState();
    setSimulationState(state);
    setJourneySummary(engine.getJourneySummary());
    if (state.status === "active") {
      setActionPreview(engine.getActionPreview());
    } else {
      setActionPreview(null);
    }
  }, []);

  const start = useCallback((lead: MockLead) => {
    const engine = new SimulationEngine(graph, lead);
    engineRef.current = engine;
    setIsActive(true);
    updateState();
  }, [graph, updateState]);

  const stop = useCallback(() => {
    if (autoPlayRef.current) {
      clearInterval(autoPlayRef.current);
      autoPlayRef.current = null;
    }
    engineRef.current = null;
    setIsActive(false);
    setSimulationState(null);
    setActionPreview(null);
    setJourneySummary(null);
  }, []);

  const next = useCallback((outcomeLabel: string) => {
    engineRef.current?.advance(outcomeLabel);
    updateState();
  }, [updateState]);

  const autoEvaluate = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return null;
    const result = engine.autoEvaluate();
    updateState();
    return { resolvedLabel: result.resolvedLabel };
  }, [updateState]);

  const autoPlay = useCallback((intervalMs = 1000) => {
    if (autoPlayRef.current) clearInterval(autoPlayRef.current);
    autoPlayRef.current = setInterval(() => {
      const engine = engineRef.current;
      if (!engine) return;
      const state = engine.getState();
      if (state.status === "completed") {
        if (autoPlayRef.current) clearInterval(autoPlayRef.current);
        autoPlayRef.current = null;
        return;
      }
      const currentNode = graph.nodes.find((n) => n.id === state.currentNodeId);
      if (currentNode?.type === "condition") {
        engine.autoEvaluate();
      } else {
        engine.advance("default");
      }
      updateState();
    }, intervalMs);
  }, [graph, updateState]);

  const stopAutoPlay = useCallback(() => {
    if (autoPlayRef.current) {
      clearInterval(autoPlayRef.current);
      autoPlayRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    engineRef.current?.reset();
    updateState();
  }, [updateState]);

  return {
    isActive,
    simulationState,
    actionPreview,
    journeySummary,
    start,
    stop,
    next,
    autoEvaluate,
    autoPlay,
    stopAutoPlay,
    reset,
  };
}
```

- [ ] **Step 4: Implement MockLeadDialog**

```tsx
// frontend/src/components/flow/MockLeadDialog.tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MockLead } from "@/lib/flow-simulation";

// Preset mock profiles for quick selection
const PRESETS: { label: string; lead: MockLead }[] = [
  {
    label: "Interested Lead",
    lead: { name: "Rahul Sharma", phone: "+919876543210", interest_level: 9, sentiment: "positive", goal_outcome: "meeting_booked" },
  },
  {
    label: "Cold Lead",
    lead: { name: "Priya Patel", phone: "+919123456780", interest_level: 3, sentiment: "negative", goal_outcome: "not_interested" },
  },
  {
    label: "No Answer Lead",
    lead: { name: "Amit Kumar", phone: "+919555555555", interest_level: 5, sentiment: "neutral", goal_outcome: "" },
  },
];

interface MockLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStart: (lead: MockLead) => void;
}

export function MockLeadDialog({ open, onOpenChange, onStart }: MockLeadDialogProps) {
  const [lead, setLead] = useState<MockLead>(PRESETS[0].lead);
  const [selectedPreset, setSelectedPreset] = useState<string>("0");

  function handlePresetChange(value: string) {
    setSelectedPreset(value);
    if (value !== "custom") {
      setLead(PRESETS[parseInt(value)].lead);
    }
  }

  function handleFieldChange(field: string, value: string | number) {
    setSelectedPreset("custom");
    setLead((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Configure Mock Lead</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Preset selector */}
          <div className="space-y-2">
            <Label>Profile Preset</Label>
            <Select value={selectedPreset} onValueChange={handlePresetChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map((p, i) => (
                  <SelectItem key={i} value={String(i)}>{p.label}</SelectItem>
                ))}
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Editable fields */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="mock-name">Name</Label>
              <Input
                id="mock-name"
                value={lead.name}
                onChange={(e) => handleFieldChange("name", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-phone">Phone</Label>
              <Input
                id="mock-phone"
                value={lead.phone}
                onChange={(e) => handleFieldChange("phone", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-interest">Interest (1-10)</Label>
              <Input
                id="mock-interest"
                type="number"
                min={1}
                max={10}
                value={lead.interest_level ?? 5}
                onChange={(e) => handleFieldChange("interest_level", parseInt(e.target.value) || 5)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-sentiment">Sentiment</Label>
              <Select
                value={lead.sentiment ?? "neutral"}
                onValueChange={(v) => handleFieldChange("sentiment", v)}
              >
                <SelectTrigger id="mock-sentiment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="positive">Positive</SelectItem>
                  <SelectItem value="neutral">Neutral</SelectItem>
                  <SelectItem value="negative">Negative</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="mock-goal">Goal Outcome</Label>
            <Input
              id="mock-goal"
              value={lead.goal_outcome ?? ""}
              onChange={(e) => handleFieldChange("goal_outcome", e.target.value)}
              placeholder="e.g. meeting_booked, callback, not_interested"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => { onStart(lead); onOpenChange(false); }}>
            Start Simulation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Implement OutcomePickerPopover**

```tsx
// frontend/src/components/flow/OutcomePickerPopover.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GitBranch, Zap } from "lucide-react";

interface OutcomePickerPopoverProps {
  /** Labels from the outgoing edges of the current condition node */
  outcomeLabels: string[];
  /** The auto-evaluated label (highlighted as recommended) */
  autoLabel?: string;
  onPick: (label: string) => void;
  onAutoEvaluate: () => void;
}

export function OutcomePickerPopover({
  outcomeLabels,
  autoLabel,
  onPick,
  onAutoEvaluate,
}: OutcomePickerPopoverProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="sm" variant="secondary" className="gap-1.5">
          <GitBranch className="h-3.5 w-3.5" />
          Pick Outcome
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-2" align="center">
        <div className="space-y-1">
          <Button
            size="sm"
            variant="ghost"
            className="w-full justify-start gap-2 text-blue-500"
            onClick={onAutoEvaluate}
          >
            <Zap className="h-3.5 w-3.5" />
            Auto-evaluate
          </Button>
          <div className="my-1 border-t" />
          {outcomeLabels.map((label) => (
            <Button
              key={label}
              size="sm"
              variant="ghost"
              className={`w-full justify-start ${label === autoLabel ? "font-semibold text-green-600" : ""}`}
              onClick={() => onPick(label)}
            >
              {label}
              {label === autoLabel && (
                <span className="ml-auto text-xs text-muted-foreground">recommended</span>
              )}
            </Button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 6: Implement SimulationToolbar**

```tsx
// frontend/src/components/flow/SimulationToolbar.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Play,
  SkipForward,
  Square,
  RotateCcw,
  FlaskConical,
  FastForward,
} from "lucide-react";
import { MockLeadDialog } from "./MockLeadDialog";
import { OutcomePickerPopover } from "./OutcomePickerPopover";
import type { UseFlowSimulationReturn } from "@/hooks/use-flow-simulation";
import type { FlowGraph } from "@/lib/flow-simulation";

interface SimulationToolbarProps {
  simulation: UseFlowSimulationReturn;
  graph: FlowGraph;
}

export function SimulationToolbar({ simulation, graph }: SimulationToolbarProps) {
  const [mockLeadOpen, setMockLeadOpen] = useState(false);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);

  const currentNode = simulation.simulationState
    ? graph.nodes.find((n) => n.id === simulation.simulationState!.currentNodeId)
    : null;

  const isCondition = currentNode?.type === "condition";
  const isCompleted = simulation.simulationState?.status === "completed";

  // Get outgoing edge labels for condition nodes
  const outcomeLabels = isCondition
    ? graph.edges
        .filter((e) => e.source === currentNode!.id)
        .map((e) => e.condition_label)
    : [];

  function handleAutoPlay() {
    if (isAutoPlaying) {
      simulation.stopAutoPlay();
      setIsAutoPlaying(false);
    } else {
      simulation.autoPlay(800);
      setIsAutoPlaying(true);
    }
  }

  if (!simulation.isActive) {
    return (
      <>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          onClick={() => setMockLeadOpen(true)}
        >
          <FlaskConical className="h-3.5 w-3.5" />
          Simulate
        </Button>
        <MockLeadDialog
          open={mockLeadOpen}
          onOpenChange={setMockLeadOpen}
          onStart={simulation.start}
        />
      </>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border bg-background/95 px-3 py-2 shadow-lg backdrop-blur">
      <Badge variant="secondary" className="bg-green-100 text-green-800">
        Simulating
      </Badge>

      {currentNode && (
        <span className="text-sm text-muted-foreground">
          @ <strong>{currentNode.name}</strong>
        </span>
      )}

      {/* Action preview */}
      {simulation.actionPreview && !isCondition && (
        <span className="max-w-xs truncate text-xs text-muted-foreground">
          {simulation.actionPreview.description}
        </span>
      )}

      <div className="mx-1 h-4 border-l" />

      {/* Step controls */}
      {!isCompleted && !isCondition && (
        <Button size="sm" variant="ghost" className="gap-1" onClick={() => simulation.next("default")}>
          <SkipForward className="h-3.5 w-3.5" />
          Next
        </Button>
      )}

      {/* Condition node: outcome picker */}
      {isCondition && (
        <OutcomePickerPopover
          outcomeLabels={outcomeLabels}
          onPick={(label) => simulation.next(label)}
          onAutoEvaluate={() => simulation.autoEvaluate()}
        />
      )}

      {/* Auto-play toggle */}
      {!isCompleted && (
        <Button
          size="sm"
          variant={isAutoPlaying ? "destructive" : "ghost"}
          className="gap-1"
          onClick={handleAutoPlay}
        >
          {isAutoPlaying ? <Square className="h-3 w-3" /> : <FastForward className="h-3.5 w-3.5" />}
          {isAutoPlaying ? "Stop" : "Auto"}
        </Button>
      )}

      {/* Completed badge */}
      {isCompleted && (
        <Badge variant="outline" className="border-green-500 text-green-700">
          Completed
        </Badge>
      )}

      <div className="mx-1 h-4 border-l" />

      <Button size="sm" variant="ghost" className="gap-1" onClick={simulation.reset}>
        <RotateCcw className="h-3.5 w-3.5" />
        Restart
      </Button>

      <Button size="sm" variant="ghost" className="gap-1 text-red-500" onClick={simulation.stop}>
        <Square className="h-3.5 w-3.5" />
        Exit
      </Button>
    </div>
  );
}
```

- [ ] **Step 7: Implement SimulationSummary**

```tsx
// frontend/src/components/flow/SimulationSummary.tsx
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Target, Route } from "lucide-react";
import type { JourneySummary } from "@/lib/flow-simulation";

interface SimulationSummaryProps {
  summary: JourneySummary;
}

export function SimulationSummary({ summary }: SimulationSummaryProps) {
  if (summary.endReason === "active") return null;

  return (
    <Card className="w-80 shadow-xl">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          Simulation Complete
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* End reason */}
        <div className="flex items-center gap-2">
          <Badge variant={summary.endReason === "goal_met" ? "default" : "secondary"}>
            {summary.endReason === "goal_met" ? "Goal Reached" : "Flow Ended"}
          </Badge>
          <span className="text-sm text-muted-foreground">
            {summary.totalSteps} nodes visited
          </span>
        </div>

        {/* Goals hit */}
        {summary.goalsHit.length > 0 && (
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <Target className="h-3 w-3" /> Goals Hit
            </div>
            <div className="flex flex-wrap gap-1">
              {summary.goalsHit.map((g) => (
                <Badge key={g} variant="outline" className="border-green-500 text-green-700">
                  {g}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Path */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            <Route className="h-3 w-3" /> Path Taken
          </div>
          <ol className="space-y-0.5">
            {summary.path.map((step, i) => (
              <li key={step.nodeId} className="flex items-center gap-2 text-sm">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium">
                  {i + 1}
                </span>
                <span>{step.nodeName}</span>
                {step.outcome && (
                  <span className="text-xs text-muted-foreground">({step.outcome})</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/use-flow-simulation.test.ts`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/hooks/use-flow-simulation.ts \
  frontend/src/hooks/__tests__/use-flow-simulation.test.ts \
  frontend/src/components/flow/SimulationToolbar.tsx \
  frontend/src/components/flow/MockLeadDialog.tsx \
  frontend/src/components/flow/OutcomePickerPopover.tsx \
  frontend/src/components/flow/SimulationSummary.tsx
git commit -m "feat: add simulation UI — toolbar, mock lead dialog, outcome picker, summary

useFlowSimulation hook wraps SimulationEngine with React state.
SimulationToolbar renders step-through and auto-play controls.
MockLeadDialog provides preset profiles and custom field editing.
OutcomePickerPopover lets users manually pick branch outcomes.
SimulationSummary shows journey recap at End/Goal nodes."
```

---

## Task 3: Canvas Integration — Path Highlighting

**Files:**
- Create: `frontend/src/components/flow/useSimulationStyles.ts`

This hook applies green highlighting to visited nodes/edges and dims unvisited ones during simulation.

- [ ] **Step 1: Write failing test for simulation styles**

```typescript
// frontend/src/components/flow/__tests__/simulation-styles.test.ts
import { describe, it, expect } from "vitest";
import { getSimulationNodeStyle, getSimulationEdgeStyle } from "../useSimulationStyles";

describe("getSimulationNodeStyle", () => {
  const visited = ["n1", "n2"];
  const currentId = "n2";

  it("highlights current node with ring", () => {
    const style = getSimulationNodeStyle("n2", visited, currentId);
    expect(style.className).toContain("ring-2");
    expect(style.className).toContain("ring-blue-500");
  });

  it("colors visited nodes green", () => {
    const style = getSimulationNodeStyle("n1", visited, currentId);
    expect(style.className).toContain("ring-green-500");
  });

  it("dims unvisited nodes", () => {
    const style = getSimulationNodeStyle("n3", visited, currentId);
    expect(style.opacity).toBe(0.35);
  });
});

describe("getSimulationEdgeStyle", () => {
  const visitedEdges = ["e1"];

  it("colors visited edges green", () => {
    const style = getSimulationEdgeStyle("e1", visitedEdges);
    expect(style.stroke).toBe("#22c55e");
    expect(style.strokeWidth).toBe(3);
  });

  it("dims unvisited edges", () => {
    const style = getSimulationEdgeStyle("e2", visitedEdges);
    expect(style.stroke).toBe("#d1d5db");
    expect(style.opacity).toBe(0.3);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/flow/__tests__/simulation-styles.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement simulation style helpers**

```typescript
// frontend/src/components/flow/useSimulationStyles.ts

export interface NodeSimStyle {
  className: string;
  opacity: number;
}

export interface EdgeSimStyle {
  stroke: string;
  strokeWidth: number;
  opacity: number;
  animated: boolean;
}

/**
 * Returns Tailwind classes and opacity for a node during simulation.
 */
export function getSimulationNodeStyle(
  nodeId: string,
  visitedNodeIds: string[],
  currentNodeId: string,
): NodeSimStyle {
  if (nodeId === currentNodeId) {
    return { className: "ring-2 ring-blue-500 ring-offset-2 shadow-lg", opacity: 1 };
  }
  if (visitedNodeIds.includes(nodeId)) {
    return { className: "ring-2 ring-green-500 ring-offset-1", opacity: 1 };
  }
  return { className: "", opacity: 0.35 };
}

/**
 * Returns stroke styles for an edge during simulation.
 */
export function getSimulationEdgeStyle(
  edgeId: string,
  visitedEdgeIds: string[],
): EdgeSimStyle {
  if (visitedEdgeIds.includes(edgeId)) {
    return { stroke: "#22c55e", strokeWidth: 3, opacity: 1, animated: true };
  }
  return { stroke: "#d1d5db", strokeWidth: 1, opacity: 0.3, animated: false };
}

/**
 * Returns styles for journey replay mode (visited = green, error = red).
 */
export function getJourneyNodeStyle(
  nodeId: string,
  visitedNodeIds: string[],
  errorNodeIds: string[],
  currentNodeId: string | null,
): NodeSimStyle {
  if (errorNodeIds.includes(nodeId)) {
    return { className: "ring-2 ring-red-500 ring-offset-1", opacity: 1 };
  }
  if (nodeId === currentNodeId) {
    return { className: "ring-2 ring-blue-500 ring-offset-2 shadow-lg animate-pulse", opacity: 1 };
  }
  if (visitedNodeIds.includes(nodeId)) {
    return { className: "ring-2 ring-green-500 ring-offset-1", opacity: 1 };
  }
  return { className: "", opacity: 0.35 };
}

export function getJourneyEdgeStyle(
  edgeId: string,
  visitedEdgeIds: string[],
): EdgeSimStyle {
  if (visitedEdgeIds.includes(edgeId)) {
    return { stroke: "#22c55e", strokeWidth: 3, opacity: 1, animated: false };
  }
  return { stroke: "#d1d5db", strokeWidth: 1, opacity: 0.3, animated: false };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/flow/__tests__/simulation-styles.test.ts`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/flow/useSimulationStyles.ts \
  frontend/src/components/flow/__tests__/simulation-styles.test.ts
git commit -m "feat: add simulation + journey replay style helpers

getSimulationNodeStyle/EdgeStyle for dry-run mode (green visited,
blue current, dimmed unvisited). getJourneyNodeStyle/EdgeStyle for
replay mode (adds red error highlighting, pulse on current node)."
```

---

## Task 4: Live Test Mode

**Files:**
- Create: `frontend/src/components/flow/LiveTestDialog.tsx`
- Create: `frontend/src/lib/flows-api.ts`
- Create: `app/api/flow_simulation.py`
- Create: `tests/test_flow_simulation.py`

- [ ] **Step 1: Write failing backend tests**

```python
# tests/test_flow_simulation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

@pytest.mark.asyncio
async def test_simulate_flow_returns_path():
    """POST /api/flows/{id}/versions/{vid}/simulate returns simulated path."""
    from app.api.flow_simulation import simulate_flow

    mock_db = AsyncMock()

    # Mock version with nodes + edges
    mock_version = MagicMock()
    mock_version.id = "v1"
    mock_version.flow_id = "f1"

    mock_nodes = [
        MagicMock(id="n1", node_type="voice_call", name="Call", config={"bot_id": "b1"}, position_x=0, position_y=0),
        MagicMock(id="n2", node_type="condition", name="Check", config={
            "conditions": [{"label": "hot", "rules": [{"field": "interest_level", "operator": "gte", "value": 7}]}],
            "default_label": "cold",
        }, position_x=0, position_y=200),
        MagicMock(id="n3", node_type="end", name="End", config={}, position_x=0, position_y=400),
    ]
    mock_edges = [
        MagicMock(id="e1", source_node_id="n1", target_node_id="n2", condition_label="default"),
        MagicMock(id="e2", source_node_id="n2", target_node_id="n3", condition_label="hot"),
        MagicMock(id="e3", source_node_id="n2", target_node_id="n3", condition_label="cold"),
    ]

    with patch("app.api.flow_simulation._get_version_graph") as mock_get:
        mock_get.return_value = (mock_nodes, mock_edges, "n1")

        result = await simulate_flow(
            db=mock_db,
            flow_id="f1",
            version_id="v1",
            org_id="org-1",
            mock_lead={"name": "Test", "phone": "+91999", "interest_level": 9},
            outcomes={},  # Let auto-evaluate handle conditions
        )

    assert len(result["path"]) == 3
    assert result["path"][0]["node_id"] == "n1"
    assert result["path"][1]["node_id"] == "n2"
    assert result["path"][2]["node_id"] == "n3"
    assert result["end_reason"] == "reached_end"


@pytest.mark.asyncio
async def test_simulate_with_manual_outcomes():
    """Manual outcomes override auto-evaluation at condition nodes."""
    from app.api.flow_simulation import simulate_flow

    mock_db = AsyncMock()

    mock_nodes = [
        MagicMock(id="n1", node_type="voice_call", name="Call", config={}, position_x=0, position_y=0),
        MagicMock(id="n2", node_type="condition", name="Check", config={
            "conditions": [{"label": "hot", "rules": [{"field": "interest_level", "operator": "gte", "value": 7}]}],
            "default_label": "cold",
        }, position_x=0, position_y=200),
        MagicMock(id="n3", node_type="whatsapp_template", name="Follow Up", config={}, position_x=-100, position_y=400),
        MagicMock(id="n4", node_type="end", name="End", config={}, position_x=100, position_y=400),
    ]
    mock_edges = [
        MagicMock(id="e1", source_node_id="n1", target_node_id="n2", condition_label="default"),
        MagicMock(id="e2", source_node_id="n2", target_node_id="n3", condition_label="hot"),
        MagicMock(id="e3", source_node_id="n2", target_node_id="n4", condition_label="cold"),
    ]

    with patch("app.api.flow_simulation._get_version_graph") as mock_get:
        mock_get.return_value = (mock_nodes, mock_edges, "n1")

        # Force "cold" even though interest_level=9 would auto-eval to "hot"
        result = await simulate_flow(
            db=mock_db,
            flow_id="f1",
            version_id="v1",
            org_id="org-1",
            mock_lead={"name": "Test", "phone": "+91999", "interest_level": 9},
            outcomes={"n2": "cold"},
        )

    assert result["path"][2]["node_id"] == "n4"  # Went to End, not Follow Up


@pytest.mark.asyncio
async def test_create_live_test_instance():
    """POST /api/flows/{id}/live-test creates instance with is_test=true."""
    from app.api.flow_simulation import create_live_test

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    # Mock the published version lookup
    mock_version = MagicMock()
    mock_version.id = "v1"
    mock_version.flow_id = "f1"

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_version
    mock_db.execute.return_value = mock_result

    with patch("app.api.flow_simulation._find_or_create_test_lead") as mock_lead, \
         patch("app.api.flow_simulation._get_entry_node_id") as mock_entry:
        mock_lead.return_value = "lead-test-1"
        mock_entry.return_value = "n1"

        result = await create_live_test(
            db=mock_db,
            flow_id="f1",
            org_id="org-1",
            phone_number="+919876543210",
            delay_ratio=60,  # 1 hour → 1 minute
        )

    assert result["is_test"] is True
    assert result["delay_ratio"] == 60
    mock_db.commit.assert_called()


@pytest.mark.asyncio
async def test_live_test_validates_phone():
    """Live test rejects invalid phone numbers."""
    from app.api.flow_simulation import create_live_test

    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="valid phone"):
        await create_live_test(
            db=mock_db,
            flow_id="f1",
            org_id="org-1",
            phone_number="invalid",
            delay_ratio=60,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flow_simulation.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement backend simulation endpoints**

```python
# app/api/flow_simulation.py
"""
Flow simulation & live test endpoints.
Spec ref: §8.1, §8.2, §12 Simulation
"""
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-simulation"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    mock_lead: dict[str, Any] = Field(..., description="Mock lead profile data")
    outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="Manual outcome overrides: {node_id: outcome_label}",
    )

class SimulatePathStep(BaseModel):
    node_id: str
    node_type: str
    node_name: str
    action_preview: str | None = None
    outcome: str | None = None

class SimulateResponse(BaseModel):
    path: list[SimulatePathStep]
    goals_hit: list[str]
    end_reason: str  # "reached_end" | "goal_met" | "no_outgoing_edge" | "max_depth"

class LiveTestRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+\d{10,15}$")
    delay_ratio: int = Field(default=60, ge=1, le=1440, description="Delay compression ratio. 60 = 1hr→1min")

class LiveTestResponse(BaseModel):
    instance_id: str
    is_test: bool
    delay_ratio: int
    phone_number: str
    status: str

# ---------------------------------------------------------------------------
# Helpers (internal)
# ---------------------------------------------------------------------------

async def _get_version_graph(db: AsyncSession, flow_id: str, version_id: str, org_id: str):
    """Load nodes + edges for a flow version. Returns (nodes, edges, entry_node_id)."""
    # Import here to avoid circular deps — models defined in Plan 2
    from app.models.flow import FlowNode, FlowEdge, FlowVersion

    version = await db.get(FlowVersion, version_id)
    if not version or str(version.flow_id) != flow_id or str(version.org_id) != org_id:
        raise HTTPException(status_code=404, detail="Flow version not found")

    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = list(nodes_result.scalars().all())

    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = list(edges_result.scalars().all())

    # Entry node = node with no incoming edges
    target_ids = {str(e.target_node_id) for e in edges}
    entry_nodes = [n for n in nodes if str(n.id) not in target_ids]
    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Flow has no entry node")

    return nodes, edges, str(entry_nodes[0].id)


async def _get_entry_node_id(db: AsyncSession, version_id: str) -> str:
    from app.models.flow import FlowNode, FlowEdge

    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = list(nodes_result.scalars().all())

    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = list(edges_result.scalars().all())

    target_ids = {str(e.target_node_id) for e in edges}
    entry_nodes = [n for n in nodes if str(n.id) not in target_ids]
    if not entry_nodes:
        raise ValueError("No entry node found")
    return str(entry_nodes[0].id)


def _evaluate_condition(config: dict, lead: dict) -> str:
    """Evaluate condition node config against lead data. Returns matching label."""
    for condition in config.get("conditions", []):
        all_match = True
        for rule in condition.get("rules", []):
            field_val = lead.get(rule["field"])
            op = rule["operator"]
            target = rule["value"]
            if op == "eq" and field_val != target:
                all_match = False
            elif op == "neq" and field_val == target:
                all_match = False
            elif op == "gte" and (not isinstance(field_val, (int, float)) or field_val < target):
                all_match = False
            elif op == "gt" and (not isinstance(field_val, (int, float)) or field_val <= target):
                all_match = False
            elif op == "lte" and (not isinstance(field_val, (int, float)) or field_val > target):
                all_match = False
            elif op == "lt" and (not isinstance(field_val, (int, float)) or field_val >= target):
                all_match = False
            elif op == "contains" and (not isinstance(field_val, str) or target not in field_val):
                all_match = False
            elif op == "regex" and (not isinstance(field_val, str) or not re.search(target, field_val)):
                all_match = False
        if all_match:
            return condition["label"]
    return config.get("default_label", "default")


def _generate_preview(node) -> str | None:
    """Generate human-readable preview for action nodes."""
    nt = node.node_type
    cfg = node.config or {}
    if nt == "voice_call":
        return f"Voice call via bot {cfg.get('bot_id', 'default')}"
    elif nt == "whatsapp_template":
        return f"WhatsApp template: {cfg.get('template_name', 'unknown')}"
    elif nt == "whatsapp_session":
        return f"WhatsApp session message"
    elif nt == "ai_generate_send":
        return f"AI-generated {cfg.get('channel', 'message')}"
    elif nt == "delay_wait":
        return f"Wait {cfg.get('duration', '?')} {cfg.get('unit', 'hours')}"
    elif nt == "wait_for_event":
        return f"Wait for {cfg.get('event_type', 'event')}"
    elif nt == "goal_met":
        return f"Goal: {cfg.get('goal_name', 'unnamed')}"
    return None


async def _find_or_create_test_lead(db: AsyncSession, org_id: str, phone: str) -> str:
    """Find existing lead by phone or create a test lead. Returns lead_id."""
    from app.models.lead import Lead

    result = await db.execute(
        select(Lead).where(Lead.org_id == org_id, Lead.phone == phone)
    )
    existing = result.scalars().first()
    if existing:
        return str(existing.id)

    lead = Lead(
        id=uuid.uuid4(),
        org_id=org_id,
        name=f"Test Lead ({phone})",
        phone=phone,
        source="flow_test",
    )
    db.add(lead)
    await db.flush()
    return str(lead.id)


# ---------------------------------------------------------------------------
# Simulation (dry-run) — pure logic, no side effects
# ---------------------------------------------------------------------------

MAX_SIMULATION_DEPTH = 100

async def simulate_flow(
    db: AsyncSession,
    flow_id: str,
    version_id: str,
    org_id: str,
    mock_lead: dict,
    outcomes: dict[str, str],
) -> dict:
    """
    Walk the flow graph using mock lead data and optional manual outcomes.
    Returns the simulated path without creating any DB records.
    """
    nodes, edges, entry_id = await _get_version_graph(db, flow_id, version_id, org_id)

    node_map = {str(n.id): n for n in nodes}
    edges_by_source: dict[str, list] = {}
    for e in edges:
        src = str(e.source_node_id)
        edges_by_source.setdefault(src, []).append(e)

    path: list[dict] = []
    goals_hit: list[str] = []
    current_id = entry_id
    visited: set[str] = set()

    for _ in range(MAX_SIMULATION_DEPTH):
        if current_id in visited:
            break  # Cycle protection
        visited.add(current_id)

        node = node_map.get(current_id)
        if not node:
            break

        step = {
            "node_id": current_id,
            "node_type": node.node_type,
            "node_name": node.name,
            "action_preview": _generate_preview(node),
            "outcome": None,
        }

        # Terminal nodes
        if node.node_type == "end":
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "reached_end"}

        if node.node_type == "goal_met":
            goals_hit.append(node.config.get("goal_name", node.name))
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "goal_met"}

        # Determine outgoing edge
        outgoing = edges_by_source.get(current_id, [])
        if not outgoing:
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "no_outgoing_edge"}

        if node.node_type == "condition":
            # Check for manual override first
            if current_id in outcomes:
                label = outcomes[current_id]
            else:
                label = _evaluate_condition(node.config or {}, mock_lead)
            step["outcome"] = label
        else:
            label = "default"
            step["outcome"] = label

        # Find matching edge
        edge = next(
            (e for e in outgoing if e.condition_label == label),
            next((e for e in outgoing if e.condition_label == "default"), None),
        )

        path.append(step)

        if not edge:
            return {"path": path, "goals_hit": goals_hit, "end_reason": "no_outgoing_edge"}

        current_id = str(edge.target_node_id)

    return {"path": path, "goals_hit": goals_hit, "end_reason": "max_depth"}


# ---------------------------------------------------------------------------
# Live Test — creates real FlowInstance with is_test=true
# ---------------------------------------------------------------------------

PHONE_PATTERN = re.compile(r"^\+\d{10,15}$")

async def create_live_test(
    db: AsyncSession,
    flow_id: str,
    org_id: str,
    phone_number: str,
    delay_ratio: int = 60,
) -> dict:
    """Create a test FlowInstance with compressed delays."""
    if not PHONE_PATTERN.match(phone_number):
        raise ValueError("Please enter a valid phone number (e.g. +919876543210)")

    from app.models.flow import FlowVersion, FlowInstance

    # Find published version
    result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.org_id == org_id,
            FlowVersion.status == "published",
        )
    )
    version = result.scalars().first()
    if not version:
        raise HTTPException(status_code=400, detail="No published version. Publish the flow first.")

    lead_id = await _find_or_create_test_lead(db, org_id, phone_number)
    entry_node_id = await _get_entry_node_id(db, str(version.id))

    instance = FlowInstance(
        id=uuid.uuid4(),
        org_id=org_id,
        flow_id=flow_id,
        version_id=version.id,
        lead_id=lead_id,
        status="active",
        current_node_id=entry_node_id,
        is_test=True,
        context_data={"delay_ratio": delay_ratio, "test_phone": phone_number},
        started_at=datetime.now(timezone.utc),
    )
    db.add(instance)
    await db.commit()

    logger.info(f"Created live test instance {instance.id} for flow {flow_id} → {phone_number}")

    return {
        "instance_id": str(instance.id),
        "is_test": True,
        "delay_ratio": delay_ratio,
        "phone_number": phone_number,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/{flow_id}/versions/{version_id}/simulate", response_model=SimulateResponse)
async def api_simulate_flow(
    flow_id: str,
    version_id: str,
    body: SimulateRequest,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Dry-run simulation of a flow version with mock lead data."""
    result = await simulate_flow(
        db=db,
        flow_id=flow_id,
        version_id=version_id,
        org_id=str(org.id),
        mock_lead=body.mock_lead,
        outcomes=body.outcomes,
    )
    return result


@router.post("/{flow_id}/live-test", response_model=LiveTestResponse)
async def api_start_live_test(
    flow_id: str,
    body: LiveTestRequest,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Start a live test with compressed delays."""
    try:
        result = await create_live_test(
            db=db,
            flow_id=flow_id,
            org_id=str(org.id),
            phone_number=body.phone_number,
            delay_ratio=body.delay_ratio,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `pytest tests/test_flow_simulation.py -v`
Expected: All tests PASS

- [ ] **Step 5: Implement flows-api.ts (frontend API client)**

```typescript
// frontend/src/lib/flows-api.ts
import { apiFetch } from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FlowSimulateRequest {
  mock_lead: Record<string, any>;
  outcomes?: Record<string, string>;
}

export interface FlowSimulatePathStep {
  node_id: string;
  node_type: string;
  node_name: string;
  action_preview: string | null;
  outcome: string | null;
}

export interface FlowSimulateResponse {
  path: FlowSimulatePathStep[];
  goals_hit: string[];
  end_reason: string;
}

export interface LiveTestRequest {
  phone_number: string;
  delay_ratio?: number;
}

export interface LiveTestResponse {
  instance_id: string;
  is_test: boolean;
  delay_ratio: number;
  phone_number: string;
  status: string;
}

export interface FlowInstanceSummary {
  id: string;
  flow_id: string;
  lead_id: string;
  lead_name?: string;
  lead_phone?: string;
  status: string;
  current_node_id: string | null;
  is_test: boolean;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface FlowTouchpointSummary {
  id: string;
  node_id: string;
  node_name?: string;
  node_type?: string;
  status: string;
  scheduled_at: string;
  executed_at: string | null;
  completed_at: string | null;
  outcome: string | null;
  generated_content: string | null;
  error_message: string | null;
}

export interface FlowTransitionSummary {
  id: string;
  from_node_id: string | null;
  to_node_id: string;
  edge_id: string | null;
  outcome_data: Record<string, any>;
  transitioned_at: string;
}

export interface JourneyData {
  instance: FlowInstanceSummary;
  touchpoints: FlowTouchpointSummary[];
  transitions: FlowTransitionSummary[];
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

/** Dry-run simulation (no side effects) */
export async function simulateFlow(
  flowId: string,
  versionId: string,
  body: FlowSimulateRequest,
): Promise<FlowSimulateResponse> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/simulate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Start a live test instance */
export async function startLiveTest(
  flowId: string,
  body: LiveTestRequest,
): Promise<LiveTestResponse> {
  return apiFetch(`/api/flows/${flowId}/live-test`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Fetch instances for a flow (for leads panel) */
export async function fetchFlowInstances(
  flowId: string,
  params?: { status?: string; is_test?: boolean; page?: number; limit?: number },
): Promise<{ instances: FlowInstanceSummary[]; total: number }> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.is_test !== undefined) search.set("is_test", String(params.is_test));
  if (params?.page) search.set("page", String(params.page));
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiFetch(`/api/flows/${flowId}/instances${qs ? `?${qs}` : ""}`);
}

/** Fetch journey data for a specific instance (for replay) */
export async function fetchJourneyData(
  flowId: string,
  instanceId: string,
): Promise<JourneyData> {
  return apiFetch(`/api/flows/${flowId}/instances/${instanceId}/journey`);
}

/** Cancel a test instance */
export async function cancelFlowInstance(
  flowId: string,
  instanceId: string,
): Promise<void> {
  return apiFetch(`/api/flows/${flowId}/instances/${instanceId}/cancel`, {
    method: "POST",
  });
}
```

- [ ] **Step 6: Implement LiveTestDialog**

```tsx
// frontend/src/components/flow/LiveTestDialog.tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Loader2, Phone, Clock } from "lucide-react";
import { startLiveTest } from "@/lib/flows-api";

interface LiveTestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flowId: string;
  onTestStarted: (instanceId: string) => void;
}

const DELAY_PRESETS = [
  { label: "Real-time (no compression)", ratio: 1 },
  { label: "10x faster (1hr → 6min)", ratio: 10 },
  { label: "60x faster (1hr → 1min)", ratio: 60 },
  { label: "360x faster (1hr → 10s)", ratio: 360 },
];

export function LiveTestDialog({
  open,
  onOpenChange,
  flowId,
  onTestStarted,
}: LiveTestDialogProps) {
  const [phone, setPhone] = useState("");
  const [delayRatio, setDelayRatio] = useState(60);
  const [loading, setLoading] = useState(false);

  async function handleStart() {
    if (!phone.match(/^\+\d{10,15}$/)) {
      toast.error("Enter a valid phone number with country code (e.g. +919876543210)");
      return;
    }

    setLoading(true);
    try {
      const result = await startLiveTest(flowId, {
        phone_number: phone,
        delay_ratio: delayRatio,
      });
      toast.success(`Live test started! Calling ${phone}...`);
      onTestStarted(result.instance_id);
      onOpenChange(false);
    } catch (err: any) {
      toast.error(err.message || "Failed to start live test");
    } finally {
      setLoading(false);
    }
  }

  function formatCompression(ratio: number): string {
    if (ratio <= 1) return "No compression";
    if (ratio < 60) return `1 hour → ${Math.round(60 / ratio)} minutes`;
    if (ratio === 60) return "1 hour → 1 minute";
    return `1 hour → ${Math.round(3600 / ratio)} seconds`;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Phone className="h-4 w-4" />
            Live Test
          </DialogTitle>
          <DialogDescription>
            Run the flow with real calls and messages to your phone.
            All delays will be compressed for faster testing.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Phone number */}
          <div className="space-y-2">
            <Label htmlFor="test-phone">Your Phone Number</Label>
            <Input
              id="test-phone"
              placeholder="+919876543210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Real calls and messages will be sent to this number.
            </p>
          </div>

          {/* Delay compression */}
          <div className="space-y-3">
            <Label className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              Delay Compression
            </Label>
            <Slider
              value={[delayRatio]}
              onValueChange={([v]) => setDelayRatio(v)}
              min={1}
              max={360}
              step={1}
              className="w-full"
            />
            <p className="text-sm font-medium">{formatCompression(delayRatio)}</p>
            <div className="flex flex-wrap gap-1.5">
              {DELAY_PRESETS.map((p) => (
                <Button
                  key={p.ratio}
                  size="sm"
                  variant={delayRatio === p.ratio ? "secondary" : "outline"}
                  onClick={() => setDelayRatio(p.ratio)}
                  className="text-xs"
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleStart} disabled={loading}>
            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Start Live Test
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add app/api/flow_simulation.py tests/test_flow_simulation.py \
  frontend/src/lib/flows-api.ts \
  frontend/src/components/flow/LiveTestDialog.tsx
git commit -m "feat: add live test mode with delay compression + backend simulation

Backend: simulate_flow() walks graph with mock lead data, supports
manual outcome overrides. create_live_test() creates FlowInstance
with is_test=true and configurable delay_ratio.
Frontend: flows-api.ts client, LiveTestDialog with phone input and
delay compression slider."
```

---

## Task 5: Journey Replay — Leads Panel + Path Overlay

**Files:**
- Create: `frontend/src/hooks/use-flow-journey.ts`
- Create: `frontend/src/components/flow/LeadsPanel.tsx`
- Create: `frontend/src/components/flow/JourneyOverlay.tsx`

- [ ] **Step 1: Write failing test for journey hook**

```typescript
// frontend/src/hooks/__tests__/use-flow-journey.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useFlowJourney } from "../use-flow-journey";

// Mock the API
vi.mock("@/lib/flows-api", () => ({
  fetchFlowInstances: vi.fn(),
  fetchJourneyData: vi.fn(),
}));

import { fetchFlowInstances, fetchJourneyData } from "@/lib/flows-api";

const MOCK_INSTANCES = {
  instances: [
    {
      id: "inst-1",
      flow_id: "f1",
      lead_id: "l1",
      lead_name: "Rahul",
      lead_phone: "+919876543210",
      status: "completed",
      current_node_id: null,
      is_test: false,
      started_at: "2026-03-20T10:00:00Z",
      completed_at: "2026-03-21T10:00:00Z",
      error_message: null,
    },
    {
      id: "inst-2",
      flow_id: "f1",
      lead_id: "l2",
      lead_name: "Priya",
      lead_phone: "+919123456780",
      status: "error",
      current_node_id: "n3",
      is_test: false,
      started_at: "2026-03-20T12:00:00Z",
      completed_at: null,
      error_message: "WhatsApp send failed",
    },
  ],
  total: 2,
};

const MOCK_JOURNEY = {
  instance: MOCK_INSTANCES.instances[0],
  touchpoints: [
    { id: "tp1", node_id: "n1", status: "completed", outcome: "picked_up", scheduled_at: "2026-03-20T10:00:00Z", executed_at: "2026-03-20T10:01:00Z", completed_at: "2026-03-20T10:05:00Z", generated_content: null, error_message: null },
    { id: "tp2", node_id: "n2", status: "completed", outcome: "interested", scheduled_at: "2026-03-20T10:05:00Z", executed_at: "2026-03-20T10:05:00Z", completed_at: "2026-03-20T10:05:00Z", generated_content: null, error_message: null },
    { id: "tp3", node_id: "n3", status: "completed", outcome: null, scheduled_at: "2026-03-20T11:00:00Z", executed_at: "2026-03-20T11:00:00Z", completed_at: "2026-03-20T11:01:00Z", generated_content: "Hi Rahul, thanks for your interest!", error_message: null },
  ],
  transitions: [
    { id: "tr1", from_node_id: null, to_node_id: "n1", edge_id: null, outcome_data: {}, transitioned_at: "2026-03-20T10:00:00Z" },
    { id: "tr2", from_node_id: "n1", to_node_id: "n2", edge_id: "e1", outcome_data: { call_outcome: "picked_up" }, transitioned_at: "2026-03-20T10:05:00Z" },
    { id: "tr3", from_node_id: "n2", to_node_id: "n3", edge_id: "e2", outcome_data: { condition: "interested" }, transitioned_at: "2026-03-20T10:05:00Z" },
  ],
};

describe("useFlowJourney", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchFlowInstances as any).mockResolvedValue(MOCK_INSTANCES);
    (fetchJourneyData as any).mockResolvedValue(MOCK_JOURNEY);
  });

  it("loads instances on mount", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));
    await waitFor(() => {
      expect(result.current.instances).toHaveLength(2);
    });
    expect(fetchFlowInstances).toHaveBeenCalledWith("f1", expect.any(Object));
  });

  it("selects an instance and loads journey", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));
    await waitFor(() => expect(result.current.instances).toHaveLength(2));

    act(() => result.current.selectInstance("inst-1"));
    await waitFor(() => {
      expect(result.current.journeyData).not.toBeNull();
    });

    expect(result.current.visitedNodeIds).toContain("n1");
    expect(result.current.visitedNodeIds).toContain("n2");
    expect(result.current.visitedNodeIds).toContain("n3");
    expect(result.current.visitedEdgeIds).toContain("e1");
    expect(result.current.visitedEdgeIds).toContain("e2");
  });

  it("identifies error nodes", async () => {
    (fetchJourneyData as any).mockResolvedValue({
      ...MOCK_JOURNEY,
      instance: MOCK_INSTANCES.instances[1],
      touchpoints: [
        ...MOCK_JOURNEY.touchpoints.slice(0, 2),
        { ...MOCK_JOURNEY.touchpoints[2], status: "failed", error_message: "Send failed" },
      ],
    });

    const { result } = renderHook(() => useFlowJourney("f1"));
    await waitFor(() => expect(result.current.instances).toHaveLength(2));

    act(() => result.current.selectInstance("inst-2"));
    await waitFor(() => expect(result.current.journeyData).not.toBeNull());

    expect(result.current.errorNodeIds).toContain("n3");
  });

  it("filters instances by status", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));
    await waitFor(() => expect(result.current.instances).toHaveLength(2));

    act(() => result.current.setStatusFilter("error"));
    await waitFor(() => {
      expect(fetchFlowInstances).toHaveBeenCalledWith("f1", expect.objectContaining({ status: "error" }));
    });
  });

  it("clears selection", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));
    await waitFor(() => expect(result.current.instances).toHaveLength(2));

    act(() => result.current.selectInstance("inst-1"));
    await waitFor(() => expect(result.current.journeyData).not.toBeNull());

    act(() => result.current.clearSelection());
    expect(result.current.selectedInstanceId).toBeNull();
    expect(result.current.journeyData).toBeNull();
    expect(result.current.visitedNodeIds).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/use-flow-journey.test.ts`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement `useFlowJourney` hook**

```typescript
// frontend/src/hooks/use-flow-journey.ts
"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchFlowInstances,
  fetchJourneyData,
  type FlowInstanceSummary,
  type JourneyData,
} from "@/lib/flows-api";

export interface UseFlowJourneyReturn {
  // Instance list
  instances: FlowInstanceSummary[];
  total: number;
  loading: boolean;
  // Filters
  statusFilter: string | null;
  setStatusFilter: (status: string | null) => void;
  // Selection
  selectedInstanceId: string | null;
  selectInstance: (id: string) => void;
  clearSelection: () => void;
  // Journey data
  journeyData: JourneyData | null;
  journeyLoading: boolean;
  // Derived canvas highlighting data
  visitedNodeIds: string[];
  visitedEdgeIds: string[];
  errorNodeIds: string[];
  currentNodeId: string | null;
  /** Map from node_id → touchpoint data for overlay display */
  touchpointByNode: Map<string, JourneyData["touchpoints"][0]>;
  /** Map from edge_id → transition data for elapsed time display */
  transitionByEdge: Map<string, JourneyData["transitions"][0]>;
  // Refresh
  refresh: () => void;
}

export function useFlowJourney(flowId: string): UseFlowJourneyReturn {
  const [instances, setInstances] = useState<FlowInstanceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [journeyData, setJourneyData] = useState<JourneyData | null>(null);
  const [journeyLoading, setJourneyLoading] = useState(false);

  // Load instances
  const loadInstances = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchFlowInstances(flowId, {
        status: statusFilter ?? undefined,
        limit: 50,
      });
      setInstances(result.instances);
      setTotal(result.total);
    } catch {
      // Silently fail — will show empty list
    } finally {
      setLoading(false);
    }
  }, [flowId, statusFilter]);

  useEffect(() => {
    loadInstances();
  }, [loadInstances]);

  // Load journey when instance selected
  const selectInstance = useCallback(async (id: string) => {
    setSelectedInstanceId(id);
    setJourneyLoading(true);
    try {
      const data = await fetchJourneyData(flowId, id);
      setJourneyData(data);
    } catch {
      setJourneyData(null);
    } finally {
      setJourneyLoading(false);
    }
  }, [flowId]);

  const clearSelection = useCallback(() => {
    setSelectedInstanceId(null);
    setJourneyData(null);
  }, []);

  // Derive highlighting data from journey
  const visitedNodeIds = journeyData
    ? journeyData.touchpoints.map((tp) => tp.node_id)
    : [];

  const visitedEdgeIds = journeyData
    ? journeyData.transitions
        .filter((t) => t.edge_id)
        .map((t) => t.edge_id!)
    : [];

  const errorNodeIds = journeyData
    ? journeyData.touchpoints
        .filter((tp) => tp.status === "failed")
        .map((tp) => tp.node_id)
    : [];

  const currentNodeId = journeyData?.instance.current_node_id ?? null;

  const touchpointByNode = new Map(
    (journeyData?.touchpoints ?? []).map((tp) => [tp.node_id, tp]),
  );

  const transitionByEdge = new Map(
    (journeyData?.transitions ?? [])
      .filter((t) => t.edge_id)
      .map((t) => [t.edge_id!, t]),
  );

  return {
    instances,
    total,
    loading,
    statusFilter,
    setStatusFilter,
    selectedInstanceId,
    selectInstance,
    clearSelection,
    journeyData,
    journeyLoading,
    visitedNodeIds,
    visitedEdgeIds,
    errorNodeIds,
    currentNodeId,
    touchpointByNode,
    transitionByEdge,
    refresh: loadInstances,
  };
}
```

- [ ] **Step 4: Implement LeadsPanel**

```tsx
// frontend/src/components/flow/LeadsPanel.tsx
"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Users,
  Search,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  PlayCircle,
  PauseCircle,
  FlaskConical,
  ChevronRight,
} from "lucide-react";
import type { UseFlowJourneyReturn } from "@/hooks/use-flow-journey";

interface LeadsPanelProps {
  journey: UseFlowJourneyReturn;
}

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  active: { icon: PlayCircle, color: "text-blue-500" },
  paused: { icon: PauseCircle, color: "text-yellow-500" },
  completed: { icon: CheckCircle2, color: "text-green-500" },
  error: { icon: AlertTriangle, color: "text-red-500" },
  cancelled: { icon: PauseCircle, color: "text-gray-500" },
};

export function LeadsPanel({ journey }: LeadsPanelProps) {
  const [search, setSearch] = useState("");

  const filtered = journey.instances.filter((inst) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      inst.lead_name?.toLowerCase().includes(q) ||
      inst.lead_phone?.includes(q)
    );
  });

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant="outline" className="gap-1.5">
          <Users className="h-3.5 w-3.5" />
          Leads
          {journey.total > 0 && (
            <Badge variant="secondary" className="ml-1 text-xs">
              {journey.total}
            </Badge>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-80 sm:w-96">
        <SheetHeader>
          <SheetTitle>Leads in Flow</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search leads..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          {/* Status filter */}
          <Select
            value={journey.statusFilter ?? "all"}
            onValueChange={(v) => journey.setStatusFilter(v === "all" ? null : v)}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="error">Error</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>

          {/* Instance list */}
          <ScrollArea className="h-[calc(100vh-220px)]">
            {journey.loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No leads in this flow yet.
              </p>
            ) : (
              <div className="space-y-1">
                {filtered.map((inst) => {
                  const statusCfg = STATUS_CONFIG[inst.status] ?? STATUS_CONFIG.active;
                  const StatusIcon = statusCfg.icon;
                  const isSelected = journey.selectedInstanceId === inst.id;

                  return (
                    <button
                      key={inst.id}
                      onClick={() =>
                        isSelected ? journey.clearSelection() : journey.selectInstance(inst.id)
                      }
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/50 ${
                        isSelected ? "bg-muted ring-1 ring-primary" : ""
                      }`}
                    >
                      <StatusIcon className={`h-4 w-4 shrink-0 ${statusCfg.color}`} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium">
                            {inst.lead_name || "Unknown"}
                          </span>
                          {inst.is_test && (
                            <FlaskConical className="h-3 w-3 text-orange-500" />
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{inst.lead_phone}</span>
                          <span>
                            {formatDistanceToNow(new Date(inst.started_at), { addSuffix: true })}
                          </span>
                        </div>
                        {inst.error_message && (
                          <p className="mt-0.5 truncate text-xs text-red-500">
                            {inst.error_message}
                          </p>
                        )}
                      </div>
                      <ChevronRight className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${isSelected ? "rotate-90" : ""}`} />
                    </button>
                  );
                })}
              </div>
            )}
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 5: Implement JourneyOverlay**

```tsx
// frontend/src/components/flow/JourneyOverlay.tsx
"use client";

import { formatDistanceToNow, format } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { X, Clock, AlertTriangle, CheckCircle2, MessageSquare } from "lucide-react";
import type { UseFlowJourneyReturn } from "@/hooks/use-flow-journey";

interface JourneyOverlayProps {
  journey: UseFlowJourneyReturn;
}

/**
 * Floating card that shows details about the selected lead's journey.
 * Renders as an overlay on the canvas when a lead is selected.
 */
export function JourneyOverlay({ journey }: JourneyOverlayProps) {
  if (!journey.journeyData) return null;

  const { instance, touchpoints } = journey.journeyData;

  return (
    <Card className="absolute bottom-4 left-4 z-50 w-80 shadow-xl">
      <CardContent className="p-4">
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">{instance.lead_name || "Unknown Lead"}</p>
            <p className="text-xs text-muted-foreground">{instance.lead_phone}</p>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge
              variant={instance.status === "error" ? "destructive" : "secondary"}
              className="text-xs"
            >
              {instance.status}
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0"
              onClick={journey.clearSelection}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Timeline */}
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Journey Timeline</p>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {touchpoints.map((tp, i) => {
              const isFailed = tp.status === "failed";
              const hasContent = !!tp.generated_content;

              return (
                <div
                  key={tp.id}
                  className={`flex items-start gap-2 rounded px-2 py-1.5 text-xs ${
                    isFailed ? "bg-red-50 dark:bg-red-950/30" : "bg-muted/30"
                  }`}
                >
                  {/* Icon */}
                  {isFailed ? (
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-green-500" />
                  )}

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium">{tp.node_name || tp.node_type}</span>
                      {tp.outcome && (
                        <Badge variant="outline" className="h-4 px-1 text-[10px]">
                          {tp.outcome}
                        </Badge>
                      )}
                    </div>

                    {/* Timestamp */}
                    {tp.executed_at && (
                      <div className="mt-0.5 flex items-center gap-1 text-muted-foreground">
                        <Clock className="h-2.5 w-2.5" />
                        <span>{format(new Date(tp.executed_at), "MMM d, HH:mm")}</span>
                      </div>
                    )}

                    {/* Generated content preview */}
                    {hasContent && (
                      <div className="mt-1 flex items-start gap-1 text-muted-foreground">
                        <MessageSquare className="mt-0.5 h-2.5 w-2.5 shrink-0" />
                        <span className="line-clamp-2">{tp.generated_content}</span>
                      </div>
                    )}

                    {/* Error message */}
                    {tp.error_message && (
                      <p className="mt-0.5 text-red-500">{tp.error_message}</p>
                    )}
                  </div>

                  {/* Elapsed time to next */}
                  {i < touchpoints.length - 1 && tp.completed_at && touchpoints[i + 1].scheduled_at && (
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {formatDistanceToNow(new Date(tp.completed_at), { addSuffix: false })}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Summary footer */}
        <div className="mt-3 flex items-center justify-between border-t pt-2 text-xs text-muted-foreground">
          <span>{touchpoints.length} nodes visited</span>
          {instance.started_at && (
            <span>
              Started {formatDistanceToNow(new Date(instance.started_at), { addSuffix: true })}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/use-flow-journey.test.ts`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/use-flow-journey.ts \
  frontend/src/hooks/__tests__/use-flow-journey.test.ts \
  frontend/src/components/flow/LeadsPanel.tsx \
  frontend/src/components/flow/JourneyOverlay.tsx
git commit -m "feat: add journey replay — leads panel, path overlay, timeline

useFlowJourney hook loads flow instances and journey data. Derives
visited/error node IDs and edge IDs for canvas highlighting.
LeadsPanel sidebar lists leads with status filter and search.
JourneyOverlay shows timeline with timestamps, outcomes, errors."
```

---

## Task 6: Backend — Journey Data Endpoint + Test Instance Tracking

**Files:**
- Modify: `app/api/flow_simulation.py`
- Create: `tests/test_flow_journey.py`

- [ ] **Step 1: Write failing tests for journey endpoint**

```python
# tests/test_flow_journey.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_fetch_flow_instances_excludes_test_by_default():
    """GET /api/flows/{id}/instances excludes is_test=true by default."""
    from app.api.flow_simulation import fetch_flow_instances

    mock_db = AsyncMock()
    instances = [
        MagicMock(id="i1", is_test=False, status="active", lead_id="l1"),
        MagicMock(id="i2", is_test=True, status="active", lead_id="l2"),
    ]

    with patch("app.api.flow_simulation._query_instances") as mock_query:
        # Returns only non-test instances
        mock_query.return_value = ([instances[0]], 1)

        result = await fetch_flow_instances(
            db=mock_db, flow_id="f1", org_id="org-1", is_test=False,
        )

    assert result["total"] == 1
    assert result["instances"][0]["id"] == "i1"


@pytest.mark.asyncio
async def test_fetch_flow_instances_includes_test_when_requested():
    """GET /api/flows/{id}/instances?is_test=true shows test instances."""
    from app.api.flow_simulation import fetch_flow_instances

    mock_db = AsyncMock()
    test_instance = MagicMock(
        id="i2", is_test=True, status="active", lead_id="l2",
        lead_name="Test Lead", lead_phone="+919876543210",
        flow_id="f1", current_node_id="n1",
        started_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
        completed_at=None, error_message=None,
    )

    with patch("app.api.flow_simulation._query_instances") as mock_query:
        mock_query.return_value = ([test_instance], 1)

        result = await fetch_flow_instances(
            db=mock_db, flow_id="f1", org_id="org-1", is_test=True,
        )

    assert result["total"] == 1
    assert result["instances"][0]["is_test"] is True


@pytest.mark.asyncio
async def test_fetch_journey_data():
    """GET /api/flows/{id}/instances/{iid}/journey returns touchpoints + transitions."""
    from app.api.flow_simulation import fetch_journey_data

    mock_db = AsyncMock()

    mock_instance = MagicMock(
        id="i1", flow_id="f1", org_id="org-1",
        status="completed", is_test=False,
    )
    mock_touchpoints = [
        MagicMock(
            id="tp1", node_id="n1", status="completed",
            outcome="picked_up", scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            executed_at=datetime(2026, 3, 20, 10, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc),
            generated_content=None, error_message=None,
        ),
    ]
    mock_transitions = [
        MagicMock(
            id="tr1", from_node_id=None, to_node_id="n1",
            edge_id=None, outcome_data={},
            transitioned_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        ),
    ]

    with patch("app.api.flow_simulation._get_instance") as mock_get, \
         patch("app.api.flow_simulation._get_touchpoints") as mock_tp, \
         patch("app.api.flow_simulation._get_transitions") as mock_tr:
        mock_get.return_value = mock_instance
        mock_tp.return_value = mock_touchpoints
        mock_tr.return_value = mock_transitions

        result = await fetch_journey_data(
            db=mock_db, flow_id="f1", instance_id="i1", org_id="org-1",
        )

    assert len(result["touchpoints"]) == 1
    assert result["touchpoints"][0]["node_id"] == "n1"
    assert len(result["transitions"]) == 1


@pytest.mark.asyncio
async def test_delay_compression_applied_to_scheduler():
    """Test instances have their delays divided by delay_ratio in context_data."""
    from app.api.flow_simulation import compute_compressed_delay

    # 1 hour delay with 60x compression = 1 minute
    result = compute_compressed_delay(delay_seconds=3600, delay_ratio=60)
    assert result == 60

    # 1 day delay with 60x compression = 24 minutes
    result = compute_compressed_delay(delay_seconds=86400, delay_ratio=60)
    assert result == 1440

    # Minimum 10 seconds even with extreme compression
    result = compute_compressed_delay(delay_seconds=60, delay_ratio=1440)
    assert result >= 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flow_journey.py -v`
Expected: FAIL — functions do not exist

- [ ] **Step 3: Add journey endpoints and helpers to flow_simulation.py**

Append to `app/api/flow_simulation.py`:

```python
# ---------------------------------------------------------------------------
# Delay compression utility
# ---------------------------------------------------------------------------

MIN_COMPRESSED_DELAY_SECONDS = 10

def compute_compressed_delay(delay_seconds: int, delay_ratio: int) -> int:
    """Apply delay compression for test instances. Returns compressed seconds."""
    if delay_ratio <= 1:
        return delay_seconds
    compressed = max(delay_seconds // delay_ratio, MIN_COMPRESSED_DELAY_SECONDS)
    return compressed


# ---------------------------------------------------------------------------
# Instance + Journey query helpers
# ---------------------------------------------------------------------------

async def _query_instances(
    db: AsyncSession,
    flow_id: str,
    org_id: str,
    status: str | None = None,
    is_test: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list, int]:
    """Query flow instances with filters. Returns (instances, total)."""
    from app.models.flow import FlowInstance
    from sqlalchemy import func

    query = select(FlowInstance).where(
        FlowInstance.flow_id == flow_id,
        FlowInstance.org_id == org_id,
    )

    if status:
        query = query.where(FlowInstance.status == status)
    if is_test is not None:
        query = query.where(FlowInstance.is_test == is_test)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch
    query = query.order_by(FlowInstance.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    instances = list(result.scalars().all())

    return instances, total


async def _get_instance(db: AsyncSession, flow_id: str, instance_id: str, org_id: str):
    from app.models.flow import FlowInstance

    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.flow_id == flow_id,
            FlowInstance.org_id == org_id,
        )
    )
    instance = result.scalars().first()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance


async def _get_touchpoints(db: AsyncSession, instance_id: str):
    from app.models.flow import FlowTouchpoint

    result = await db.execute(
        select(FlowTouchpoint)
        .where(FlowTouchpoint.instance_id == instance_id)
        .order_by(FlowTouchpoint.scheduled_at)
    )
    return list(result.scalars().all())


async def _get_transitions(db: AsyncSession, instance_id: str):
    from app.models.flow import FlowTransition

    result = await db.execute(
        select(FlowTransition)
        .where(FlowTransition.instance_id == instance_id)
        .order_by(FlowTransition.transitioned_at)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

async def fetch_flow_instances(
    db: AsyncSession,
    flow_id: str,
    org_id: str,
    status: str | None = None,
    is_test: bool = False,
    limit: int = 50,
    page: int = 1,
) -> dict:
    """Fetch paginated flow instances."""
    offset = (page - 1) * limit
    instances, total = await _query_instances(
        db, flow_id, org_id, status=status, is_test=is_test, limit=limit, offset=offset,
    )

    return {
        "instances": [
            {
                "id": str(inst.id),
                "flow_id": str(inst.flow_id),
                "lead_id": str(inst.lead_id),
                "lead_name": getattr(inst, "lead_name", None),
                "lead_phone": getattr(inst, "lead_phone", None),
                "status": inst.status,
                "current_node_id": str(inst.current_node_id) if inst.current_node_id else None,
                "is_test": inst.is_test,
                "started_at": inst.started_at.isoformat() if inst.started_at else None,
                "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
                "error_message": inst.error_message,
            }
            for inst in instances
        ],
        "total": total,
    }


async def fetch_journey_data(
    db: AsyncSession,
    flow_id: str,
    instance_id: str,
    org_id: str,
) -> dict:
    """Fetch full journey data for replay: instance + touchpoints + transitions."""
    instance = await _get_instance(db, flow_id, instance_id, org_id)
    touchpoints = await _get_touchpoints(db, instance_id)
    transitions = await _get_transitions(db, instance_id)

    return {
        "instance": {
            "id": str(instance.id),
            "flow_id": str(instance.flow_id),
            "lead_id": str(instance.lead_id),
            "status": instance.status,
            "current_node_id": str(instance.current_node_id) if instance.current_node_id else None,
            "is_test": instance.is_test,
            "started_at": instance.started_at.isoformat() if instance.started_at else None,
            "completed_at": instance.completed_at.isoformat() if instance.completed_at else None,
            "error_message": instance.error_message,
        },
        "touchpoints": [
            {
                "id": str(tp.id),
                "node_id": str(tp.node_id),
                "status": tp.status,
                "outcome": tp.outcome,
                "scheduled_at": tp.scheduled_at.isoformat() if tp.scheduled_at else None,
                "executed_at": tp.executed_at.isoformat() if tp.executed_at else None,
                "completed_at": tp.completed_at.isoformat() if tp.completed_at else None,
                "generated_content": tp.generated_content,
                "error_message": tp.error_message,
            }
            for tp in touchpoints
        ],
        "transitions": [
            {
                "id": str(t.id),
                "from_node_id": str(t.from_node_id) if t.from_node_id else None,
                "to_node_id": str(t.to_node_id),
                "edge_id": str(t.edge_id) if t.edge_id else None,
                "outcome_data": t.outcome_data or {},
                "transitioned_at": t.transitioned_at.isoformat() if t.transitioned_at else None,
            }
            for t in transitions
        ],
    }


# ---------------------------------------------------------------------------
# Additional Routes
# ---------------------------------------------------------------------------

@router.get("/{flow_id}/instances")
async def api_fetch_instances(
    flow_id: str,
    status: str | None = None,
    is_test: bool = False,
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """List flow instances for the leads panel."""
    return await fetch_flow_instances(
        db=db, flow_id=flow_id, org_id=str(org.id),
        status=status, is_test=is_test, page=page, limit=limit,
    )


@router.get("/{flow_id}/instances/{instance_id}/journey")
async def api_fetch_journey(
    flow_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Fetch full journey data for a specific instance (replay mode)."""
    return await fetch_journey_data(
        db=db, flow_id=flow_id, instance_id=instance_id, org_id=str(org.id),
    )


@router.post("/{flow_id}/instances/{instance_id}/cancel")
async def api_cancel_instance(
    flow_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Cancel a flow instance (typically used for test instances)."""
    instance = await _get_instance(db, flow_id, instance_id, str(org.id))

    if instance.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Instance already {instance.status}")

    instance.status = "cancelled"
    instance.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"status": "cancelled", "instance_id": str(instance.id)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_flow_journey.py tests/test_flow_simulation.py -v`
Expected: All tests PASS

- [ ] **Step 5: Wire router into main app**

In `app/main.py`, add the flow simulation router:

```python
# At the top with other imports:
from app.api.flow_simulation import router as flow_simulation_router

# In the app setup (after other router includes):
app.include_router(flow_simulation_router)
```

- [ ] **Step 6: Commit**

```bash
git add app/api/flow_simulation.py app/main.py \
  tests/test_flow_journey.py
git commit -m "feat: add journey data endpoints + delay compression + instance management

Journey replay: GET /instances lists leads in flow, GET /instances/{id}/journey
returns touchpoints + transitions for path highlighting.
Delay compression: compute_compressed_delay() divides wait times by ratio.
Instance cancel endpoint for stopping test runs."
```

---

## Task 7: Integration — Wire Simulation Into Canvas

**Files:**
- This task describes the wiring needed in the FlowCanvas component (built in Plan 3)

- [ ] **Step 1: Document canvas integration points**

The FlowCanvas component (from Plan 3) needs these additions. This is pseudo-code showing where each piece plugs in — exact integration depends on Plan 3's component structure.

```tsx
// frontend/src/app/(app)/flows/[id]/canvas/page.tsx
// (or wherever FlowCanvas is defined in Plan 3)

// Additional imports for simulation
import { useFlowSimulation } from "@/hooks/use-flow-simulation";
import { useFlowJourney } from "@/hooks/use-flow-journey";
import { SimulationToolbar } from "@/components/flow/SimulationToolbar";
import { SimulationSummary } from "@/components/flow/SimulationSummary";
import { LiveTestDialog } from "@/components/flow/LiveTestDialog";
import { LeadsPanel } from "@/components/flow/LeadsPanel";
import { JourneyOverlay } from "@/components/flow/JourneyOverlay";
import {
  getSimulationNodeStyle,
  getSimulationEdgeStyle,
  getJourneyNodeStyle,
  getJourneyEdgeStyle,
} from "@/components/flow/useSimulationStyles";

// Inside the canvas component:
export default function FlowCanvasPage() {
  // ... existing Plan 3 state (nodes, edges, version, etc.)

  // --- Simulation ---
  const graph: FlowGraph = {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      name: n.data.name,
      config: n.data.config,
      position: n.position,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      condition_label: e.data?.conditionLabel ?? "default",
    })),
    entryNodeId: nodes.find((n) => /* no incoming edges */)?.id ?? nodes[0]?.id,
  };

  const simulation = useFlowSimulation(graph);
  const journey = useFlowJourney(flowId);
  const [liveTestOpen, setLiveTestOpen] = useState(false);

  // --- Apply visual styles ---
  // In the node rendering, apply simulation/journey styles:
  const getNodeClassName = (nodeId: string) => {
    if (simulation.isActive && simulation.simulationState) {
      return getSimulationNodeStyle(
        nodeId,
        simulation.simulationState.visitedNodeIds,
        simulation.simulationState.currentNodeId,
      );
    }
    if (journey.selectedInstanceId) {
      return getJourneyNodeStyle(
        nodeId,
        journey.visitedNodeIds,
        journey.errorNodeIds,
        journey.currentNodeId,
      );
    }
    return { className: "", opacity: 1 };
  };

  const getEdgeStyle = (edgeId: string) => {
    if (simulation.isActive && simulation.simulationState) {
      return getSimulationEdgeStyle(edgeId, simulation.simulationState.visitedEdgeIds);
    }
    if (journey.selectedInstanceId) {
      return getJourneyEdgeStyle(edgeId, journey.visitedEdgeIds);
    }
    return { stroke: "#64748b", strokeWidth: 2, opacity: 1, animated: false };
  };

  return (
    <div className="relative h-full">
      {/* Canvas Toolbar — add simulation + test buttons */}
      <div className="absolute left-1/2 top-4 z-50 -translate-x-1/2">
        {simulation.isActive ? (
          <SimulationToolbar simulation={simulation} graph={graph} />
        ) : (
          <div className="flex items-center gap-2">
            {/* ... existing toolbar buttons from Plan 3 */}
            <SimulationToolbar simulation={simulation} graph={graph} />
            <Button
              size="sm"
              variant="outline"
              onClick={() => setLiveTestOpen(true)}
            >
              Live Test
            </Button>
            <LeadsPanel journey={journey} />
          </div>
        )}
      </div>

      {/* React Flow canvas with styled nodes/edges */}
      <ReactFlow
        nodes={nodes.map((n) => ({
          ...n,
          data: { ...n.data, simStyle: getNodeClassName(n.id) },
        }))}
        edges={edges.map((e) => ({
          ...e,
          style: getEdgeStyle(e.id),
          animated: getEdgeStyle(e.id).animated,
        }))}
        // ... other React Flow props
      />

      {/* Simulation summary overlay */}
      {simulation.isActive && simulation.journeySummary?.endReason !== "active" && (
        <div className="absolute bottom-4 right-4 z-50">
          <SimulationSummary summary={simulation.journeySummary!} />
        </div>
      )}

      {/* Journey replay overlay */}
      <JourneyOverlay journey={journey} />

      {/* Live test dialog */}
      <LiveTestDialog
        open={liveTestOpen}
        onOpenChange={setLiveTestOpen}
        flowId={flowId}
        onTestStarted={(instanceId) => {
          journey.refresh();
          toast.success("Live test started — check the Leads panel to track progress");
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify all component exports are correct**

Run:
```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```
Expected: No type errors in simulation/journey files

- [ ] **Step 3: Commit integration**

```bash
git commit -m "docs: document canvas integration points for simulation + journey replay

Task 7 of Plan 5 describes how SimulationToolbar, LeadsPanel,
JourneyOverlay, and style helpers wire into the FlowCanvas component
from Plan 3."
```

---

## Summary

| Task | What it does | Files |
|------|-------------|-------|
| 1 | Client-side graph walker engine | `flow-simulation.ts`, tests |
| 2 | Simulation React hook + UI controls | `use-flow-simulation.ts`, toolbar, dialogs |
| 3 | Canvas path highlighting styles | `useSimulationStyles.ts`, tests |
| 4 | Live test mode (backend + frontend) | `flow_simulation.py`, `flows-api.ts`, `LiveTestDialog` |
| 5 | Journey replay (leads panel + overlay) | `use-flow-journey.ts`, `LeadsPanel`, `JourneyOverlay` |
| 6 | Backend journey endpoints + delay compression | `flow_simulation.py` additions, tests |
| 7 | Canvas integration wiring | Integration doc in canvas page |

**Total:** 7 tasks, ~35 steps, 7 commits.

**Dependencies:**
- Tasks 1-3 are frontend-only and can start immediately after Plan 3 (canvas).
- Task 4 requires Plan 2 (FlowInstance model) and Plan 4 (flow engine scheduler for delay compression).
- Tasks 5-6 require Plan 2 (FlowTouchpoint, FlowTransition models).
- Task 7 requires Plan 3 (FlowCanvas component) + all prior tasks in this plan.

After completing this plan, the flow builder will support full simulation, live testing, and journey replay capabilities as specified in §8 of the design spec.
