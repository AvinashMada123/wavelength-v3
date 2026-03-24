// frontend/src/components/flow/nodes/DeleteNodeButton.tsx
"use client";

import { useReactFlow } from "@xyflow/react";
import { X } from "lucide-react";
import { useFlowDraft } from "../FlowDraftContext";

interface DeleteNodeButtonProps {
  nodeId: string;
}

/**
 * Small delete button shown at the top-right corner of a node on hover.
 * Only visible when the flow is in draft mode.
 */
export function DeleteNodeButton({ nodeId }: DeleteNodeButtonProps) {
  const isDraft = useFlowDraft();
  const { deleteElements } = useReactFlow();

  if (!isDraft) return null;

  return (
    <button
      type="button"
      className="absolute -right-2 -top-2 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-destructive text-destructive-foreground opacity-0 shadow-sm transition-opacity group-hover:opacity-100 hover:bg-destructive/90"
      onClick={(e) => {
        e.stopPropagation();
        deleteElements({ nodes: [{ id: nodeId }] });
      }}
      title="Delete node"
    >
      <X className="h-3 w-3" />
    </button>
  );
}
