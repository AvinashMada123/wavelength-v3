// frontend/src/components/flow/nodes/EndNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CircleStop } from "lucide-react";

function EndNodeComponent({ data, selected }: NodeProps) {
  return (
    <div
      className={`rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-red-500 ring-2 ring-red-500/20" : "border-red-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <Handle type="target" position={Position.Top} className="!bg-red-500" />
      <div className="flex items-center gap-2">
        <CircleStop className="h-4 w-4 text-red-500" />
        <span className="text-sm font-medium">{(data.label as string) || "End"}</span>
      </div>
    </div>
  );
}

export const EndNode = memo(EndNodeComponent);
