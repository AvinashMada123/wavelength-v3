// frontend/src/components/flow/nodes/WhatsAppSessionNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { MessageCircle } from "lucide-react";

function WhatsAppSessionNodeComponent({ data, selected }: NodeProps) {
  return (
    <div
      className={`rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-emerald-500 ring-2 ring-emerald-500/20" : "border-emerald-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <Handle type="target" position={Position.Top} className="!bg-emerald-500" />
      <div className="flex items-center gap-2">
        <MessageCircle className="h-4 w-4 text-emerald-500" />
        <span className="text-sm font-medium">{(data.label as string) || "WhatsApp Session"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-emerald-500" />
    </div>
  );
}

export const WhatsAppSessionNode = memo(WhatsAppSessionNodeComponent);
