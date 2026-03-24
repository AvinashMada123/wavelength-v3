// frontend/src/components/flow/nodes/WhatsAppTemplateNode.tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { MessageSquare } from "lucide-react";
import { DeleteNodeButton } from "./DeleteNodeButton";

function WhatsAppTemplateNodeComponent({ id, data, selected }: NodeProps) {
  return (
    <div
      className={`group relative rounded-lg border-2 bg-background px-4 py-3 shadow-sm transition-colors ${
        selected ? "border-green-500 ring-2 ring-green-500/20" : "border-green-300"
      }`}
      style={{ minWidth: 180 }}
    >
      <DeleteNodeButton nodeId={id} />
      <Handle type="target" position={Position.Top} className="!bg-green-500" />
      <div className="flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-green-500" />
        <span className="text-sm font-medium">{(data.label as string) || "WhatsApp Template"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-green-500" />
    </div>
  );
}

export const WhatsAppTemplateNode = memo(WhatsAppTemplateNodeComponent);
