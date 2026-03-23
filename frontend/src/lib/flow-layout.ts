// frontend/src/lib/flow-layout.ts

import type { Node, Edge } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Simple auto-layout using a topological sort approach
// (dagre-free to avoid extra dependency; positions nodes in a grid)
// ---------------------------------------------------------------------------

const NODE_WIDTH = 220;
const NODE_HEIGHT = 80;
const HORIZONTAL_GAP = 80;
const VERTICAL_GAP = 100;

/**
 * Apply a simple dagre-like layout to nodes based on their edges.
 * Nodes are arranged top-to-bottom following the graph topology.
 */
export function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // Build adjacency
  const children = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  for (const node of nodes) {
    children.set(node.id, []);
    inDegree.set(node.id, 0);
  }

  for (const edge of edges) {
    children.get(edge.source)?.push(edge.target);
    inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
  }

  // Topological sort (BFS / Kahn's)
  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  const layers: string[][] = [];
  const visited = new Set<string>();

  while (queue.length > 0) {
    const layer = [...queue];
    layers.push(layer);
    queue.length = 0;

    for (const id of layer) {
      visited.add(id);
      for (const child of children.get(id) || []) {
        const newDeg = (inDegree.get(child) || 1) - 1;
        inDegree.set(child, newDeg);
        if (newDeg === 0 && !visited.has(child)) {
          queue.push(child);
        }
      }
    }
  }

  // Add any unvisited nodes (cycles or disconnected) to the last layer
  for (const node of nodes) {
    if (!visited.has(node.id)) {
      if (layers.length === 0) layers.push([]);
      layers[layers.length - 1].push(node.id);
    }
  }

  // Assign positions
  const positionMap = new Map<string, { x: number; y: number }>();

  for (let row = 0; row < layers.length; row++) {
    const layer = layers[row];
    const totalWidth = layer.length * NODE_WIDTH + (layer.length - 1) * HORIZONTAL_GAP;
    const startX = -totalWidth / 2;

    for (let col = 0; col < layer.length; col++) {
      positionMap.set(layer[col], {
        x: startX + col * (NODE_WIDTH + HORIZONTAL_GAP),
        y: row * (NODE_HEIGHT + VERTICAL_GAP),
      });
    }
  }

  return nodes.map((node) => ({
    ...node,
    position: positionMap.get(node.id) || node.position,
  }));
}
