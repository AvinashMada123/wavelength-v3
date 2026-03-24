// frontend/src/components/flow/nodes/VoiceCallNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Phone } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function VoiceCallNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-blue-500 ring-2 ring-blue-500/20" : "border-blue-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-blue-500" />
      <div className="flex items-center gap-2">
        <Phone className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium">{(data.label as string) || "Voice Call"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-blue-500" />
    </div>
  );
}

export const VoiceCallNode = memo(VoiceCallNodeComponent);
