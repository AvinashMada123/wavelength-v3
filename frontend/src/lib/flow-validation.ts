// frontend/src/lib/flow-validation.ts

import type { Node, Edge } from "@xyflow/react";
import type { ValidationResult, ValidationIssue } from "./flow-types";

const TRIGGER_TYPES = new Set(["trigger_post_call", "trigger_manual", "trigger_campaign_complete"]);
const TERMINAL_TYPES = new Set(["end"]);

/**
 * Client-side flow graph validation.
 * Provides instant feedback before server-side validation.
 */
export function validateFlowGraph(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];

  if (nodes.length === 0) {
    errors.push({ message: "Flow has no nodes. Start by adding a Trigger.", node_id: null, severity: "error" });
    return { valid: false, errors, warnings };
  }

  // ── Trigger validation ──────────────────────────────────────────────
  const triggerNodes = nodes.filter((n) => TRIGGER_TYPES.has(n.type || ""));

  if (triggerNodes.length === 0) {
    errors.push({
      message: "Flow needs a Trigger node. Drag one from the Triggers section.",
      node_id: null,
      severity: "error",
    });
  }

  if (triggerNodes.length > 1) {
    errors.push({
      message: `Only one Trigger allowed per flow (found ${triggerNodes.length})`,
      node_id: triggerNodes[1].id,
      severity: "error",
    });
  }

  // Trigger should have no incoming edges
  const nodesWithIncoming = new Set(edges.map((e) => e.target));
  for (const trigger of triggerNodes) {
    if (nodesWithIncoming.has(trigger.id)) {
      errors.push({
        message: `"${trigger.data.label || "Trigger"}" should not have incoming edges — it's the starting point`,
        node_id: trigger.id,
        severity: "error",
      });
    }
  }

  // Trigger must have at least one outgoing edge
  const nodesWithOutgoing = new Set(edges.map((e) => e.source));
  for (const trigger of triggerNodes) {
    if (!nodesWithOutgoing.has(trigger.id)) {
      warnings.push({
        message: `"${trigger.data.label || "Trigger"}" has no outgoing connection — connect it to your first action`,
        node_id: trigger.id,
        severity: "warning",
      });
    }
  }

  // ── End node validation ─────────────────────────────────────────────
  const endNodes = nodes.filter((n) => TERMINAL_TYPES.has(n.type || ""));
  if (endNodes.length === 0) {
    errors.push({
      message: "Flow needs at least one End node",
      node_id: null,
      severity: "error",
    });
  }

  // ── Dead-end detection ──────────────────────────────────────────────
  for (const node of nodes) {
    const type = node.type || "";
    if (!nodesWithOutgoing.has(node.id) && !TERMINAL_TYPES.has(type) && type !== "goal_met") {
      warnings.push({
        message: `"${node.data.label || type}" has no outgoing edges — leads will get stuck here`,
        node_id: node.id,
        severity: "warning",
      });
    }
  }

  // ── Disconnected nodes ──────────────────────────────────────────────
  const connectedNodes = new Set([
    ...edges.map((e) => e.source),
    ...edges.map((e) => e.target),
  ]);
  for (const node of nodes) {
    if (!connectedNodes.has(node.id) && nodes.length > 1) {
      warnings.push({
        message: `"${node.data.label || node.type}" is disconnected from the flow`,
        node_id: node.id,
        severity: "warning",
      });
    }
  }

  // ── Config validation ───────────────────────────────────────────────
  for (const node of nodes) {
    const config = node.data.config as Record<string, unknown> | undefined;

    if (node.type === "voice_call" && !config?.bot_id) {
      errors.push({
        message: `"${node.data.label || "Voice Call"}" has no bot selected`,
        node_id: node.id,
        severity: "error",
      });
    }

    if (node.type === "whatsapp_template" && !config?.template_name) {
      errors.push({
        message: `"${node.data.label || "WhatsApp Template"}" has no template name`,
        node_id: node.id,
        severity: "error",
      });
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}
