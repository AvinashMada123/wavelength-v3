// frontend/src/hooks/use-flow-history.ts

import { useCallback, useRef } from "react";
import type { Node, Edge } from "@xyflow/react";

interface HistoryEntry {
  nodes: Node[];
  edges: Edge[];
  description: string;
}

/**
 * Undo/redo history for flow canvas state.
 */
export function useFlowHistory() {
  const undoStack = useRef<HistoryEntry[]>([]);
  const redoStack = useRef<HistoryEntry[]>([]);

  const pushState = useCallback((nodes: Node[], edges: Edge[], description: string) => {
    undoStack.current.push({
      nodes: structuredClone(nodes),
      edges: structuredClone(edges),
      description,
    });
    // Clear redo stack on new action
    redoStack.current = [];
  }, []);

  const undo = useCallback(
    (currentNodes: Node[], currentEdges: Edge[]): HistoryEntry | null => {
      const entry = undoStack.current.pop();
      if (!entry) return null;

      // Push current state to redo stack
      redoStack.current.push({
        nodes: structuredClone(currentNodes),
        edges: structuredClone(currentEdges),
        description: entry.description,
      });

      return entry;
    },
    [],
  );

  const redo = useCallback(
    (currentNodes: Node[], currentEdges: Edge[]): HistoryEntry | null => {
      const entry = redoStack.current.pop();
      if (!entry) return null;

      // Push current state to undo stack
      undoStack.current.push({
        nodes: structuredClone(currentNodes),
        edges: structuredClone(currentEdges),
        description: entry.description,
      });

      return entry;
    },
    [],
  );

  return {
    pushState,
    undo,
    redo,
    canUndo: undoStack.current.length > 0,
    canRedo: redoStack.current.length > 0,
  };
}
