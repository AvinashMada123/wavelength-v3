"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Zap, Play, Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { DeleteNodeButton } from "./DeleteNodeButton";

const TRIGGER_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  trigger_post_call: Zap,
  trigger_manual: Play,
  trigger_campaign_complete: Flag,
};

const TRIGGER_LABELS: Record<string, string> = {
  trigger_post_call: "Post Call",
  trigger_manual: "Manual Trigger",
  trigger_campaign_complete: "Campaign Complete",
};

const TRIGGER_DESCRIPTIONS: Record<string, string> = {
  trigger_post_call: "Flow starts when a call ends",
  trigger_manual: "Flow starts when you enroll a lead",
  trigger_campaign_complete: "Flow starts when campaign finishes",
};

export function TriggerNode({ id, data, selected }: NodeProps) {
  const nodeType = String(data.nodeType ?? "trigger_manual");
  const Icon = TRIGGER_ICONS[nodeType] || Zap;
  const label: string = String(data.label ?? TRIGGER_LABELS[nodeType] ?? "Trigger");
  const description: string = TRIGGER_DESCRIPTIONS[nodeType] || "";
  const config = (data.config ?? {}) as Record<string, unknown>;

  return (
    <div
      className={cn(
        "group relative min-w-[200px] rounded-lg border-2 bg-background shadow-md transition-all",
        "border-orange-500",
        selected && "ring-2 ring-orange-400 ring-offset-2 ring-offset-background",
      )}
    >
      <DeleteNodeButton nodeId={id} />
      {/* Header */}
      <div className="flex items-center gap-2 rounded-t-md bg-orange-500/10 px-3 py-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-orange-500/20">
          <Icon className="h-4 w-4 text-orange-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">{label}</p>
          <p className="text-[10px] text-muted-foreground">{description}</p>
        </div>
      </div>

      {/* Config preview */}
      {nodeType === "trigger_post_call" && (
        <div className="border-t border-border/50 px-3 py-2">
          <p className="text-[10px] text-muted-foreground">
            {config.goal_outcome ? `Goal: ${String(config.goal_outcome)}` : "All call outcomes"}
          </p>
        </div>
      )}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-3 !w-3 !border-2 !border-orange-500 !bg-background"
      />
    </div>
  );
}

// All three trigger types use the same component
export const PostCallTriggerNode = TriggerNode;
export const ManualTriggerNode = TriggerNode;
export const CampaignCompleteTriggerNode = TriggerNode;
