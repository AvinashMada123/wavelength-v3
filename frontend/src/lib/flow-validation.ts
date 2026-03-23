// frontend/src/lib/flow-validation.ts

import type { Node, Edge } from "@xyflow/react";
import type { ValidationResult, ValidationIssue } from "./flow-types";

/**
 * Client-side flow graph validation.
 * Provides instant feedback before server-side validation.
 */
export function validateFlowGraph(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];

  if (nodes.length === 0) {
    errors.push({ message: "Flow has no nodes", node_id: null, severity: "error" });
    return { valid: false, errors, warnings };
  }

  // Check for nodes with no incoming edges (except first / entry nodes)
  const nodesWithIncoming = new Set(edges.map((e) => e.target));
  const entryNodes = nodes.filter((n) => !nodesWithIncoming.has(n.id));

  if (entryNodes.length === 0) {
    warnings.push({
      message: "No entry node found — every node has incoming edges (possible cycle)",
      node_id: null,
      severity: "warning",
    });
  }

  if (entryNodes.length > 1) {
    warnings.push({
      message: `Multiple entry nodes found (${entryNodes.length}). Consider having a single starting node.`,
      node_id: null,
      severity: "warning",
    });
  }

  // Check for nodes with no outgoing edges (should be terminal nodes)
  const nodesWithOutgoing = new Set(edges.map((e) => e.source));
  const terminalTypes = new Set(["end", "goal_met"]);

  for (const node of nodes) {
    if (!nodesWithOutgoing.has(node.id) && !terminalTypes.has(node.type || "")) {
      warnings.push({
        message: `"${node.data.label || node.type}" has no outgoing edges — leads will stop here`,
        node_id: node.id,
        severity: "warning",
      });
    }
  }

  // Check voice_call nodes have a bot configured
  for (const node of nodes) {
    if (node.type === "voice_call") {
      const config = node.data.config as Record<string, any> | undefined;
      if (!config?.bot_id) {
        errors.push({
          message: `"${node.data.label || "Voice Call"}" has no bot selected`,
          node_id: node.id,
          severity: "error",
        });
      }
    }
  }

  // Check whatsapp_template nodes have a template name
  for (const node of nodes) {
    if (node.type === "whatsapp_template") {
      const config = node.data.config as Record<string, any> | undefined;
      if (!config?.template_name) {
        errors.push({
          message: `"${node.data.label || "WhatsApp Template"}" has no template name`,
          node_id: node.id,
          severity: "error",
        });
      }
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}
