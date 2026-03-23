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
