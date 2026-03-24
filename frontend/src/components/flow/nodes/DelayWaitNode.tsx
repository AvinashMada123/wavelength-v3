// frontend/src/components/flow/nodes/DelayWaitNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Clock } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function DelayWaitNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-slate-500 ring-2 ring-slate-500/20" : "border-slate-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-slate-500" />
      <div className="flex items-center gap-2">
        <Clock className="h-4 w-4 text-slate-500" />
        <span className="text-sm font-medium">{(data.label as string) || "Delay / Wait"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500" />
    </div>
  );
}

export const DelayWaitNode = memo(DelayWaitNodeComponent);
