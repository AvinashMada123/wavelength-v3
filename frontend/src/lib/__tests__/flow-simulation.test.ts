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
