// frontend/src/components/flow/nodes/ConditionNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitBranch } from "lucide-react";

function ConditionNodeComponent({ data, selected }: NodeProps) {
  return (
    <div
      className={`rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-amber-500 ring-2 ring-amber-500/20" : "border-amber-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <Handle type="target" position={Position.Top} className="!bg-amber-500" />
      <div className="flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium">{(data.label as string) || "Condition"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} id="true" className="!bg-amber-500 !left-[30%]" />
      <Handle type="source" position={Position.Bottom} id="false" className="!bg-amber-500 !left-[70%]" />
    </div>
  );
}

export const ConditionNode = memo(ConditionNodeComponent);
