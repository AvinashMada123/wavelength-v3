// frontend/src/components/flow/nodes/WaitForEventNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Bell } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function WaitForEventNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-cyan-500 ring-2 ring-cyan-500/20" : "border-cyan-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-cyan-500" />
      <div className="flex items-center gap-2">
        <Bell className="h-4 w-4 text-cyan-500" />
        <span className="text-sm font-medium">{(data.label as string) || "Wait for Event"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} id="received" className="!bg-cyan-500 !left-[30%]" />
      <Handle type="source" position={Position.Bottom} id="timeout" className="!bg-cyan-500 !left-[70%]" />
    </div>
  );
}

export const WaitForEventNode = memo(WaitForEventNodeComponent);
