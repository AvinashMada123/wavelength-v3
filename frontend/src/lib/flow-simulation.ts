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
