// frontend/src/components/flow/nodes/AIGenerateNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Sparkles } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function AIGenerateNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-purple-500 ring-2 ring-purple-500/20" : "border-purple-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-purple-500" />
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-purple-500" />
        <span className="text-sm font-medium">{(data.label as string) || "AI Generate & Send"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-purple-500" />
    </div>
  );
}

export const AIGenerateNode = memo(AIGenerateNodeComponent);
