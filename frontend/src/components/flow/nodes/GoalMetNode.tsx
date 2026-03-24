// frontend/src/components/flow/nodes/GoalMetNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Target } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function GoalMetNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-emerald-500 ring-2 ring-emerald-500/20" : "border-emerald-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-emerald-500" />
      <div className="flex items-center gap-2">
        <Target className="h-4 w-4 text-emerald-500" />
        <span className="text-sm font-medium">{(data.label as string) || "Goal Met"}</span>
      </div>
    </div>
  );
}

export const GoalMetNode = memo(GoalMetNodeComponent);
