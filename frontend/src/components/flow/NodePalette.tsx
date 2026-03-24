// frontend/src/components/flow/NodePalette.tsx
"use client";

import { type DragEvent, useCallback } from "react";
import {
  Phone,
  MessageSquare,
  MessageCircle,
  Sparkles,
  GitBranch,
  Clock,
  Bell,
  Target,
  CircleStop,
  Zap,
  Play,
  Flag,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NODE_TYPE_REGISTRY, type FlowNodeType } from "@/lib/flow-types";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Phone, MessageSquare, MessageCircle, Sparkles, GitBranch, Clock, Bell,
  Target, CircleStop, Zap, Play, Flag,
};

const CATEGORIES = [
  {
    key: "trigger" as const,
    label: "Triggers",
    description: "What starts the flow",
    accent: "text-orange-400",
  },
  {
    key: "action" as const,
    label: "Actions",
    description: "Do something",
    accent: "text-blue-400",
  },
  {
    key: "logic" as const,
    label: "Logic",
    description: "Control the flow",
    accent: "text-amber-400",
  },
];

interface NodePaletteProps {
  className?: string;
}

export function NodePalette({ className }: NodePaletteProps) {
  const onDragStart = useCallback(
    (event: DragEvent<HTMLDivElement>, nodeType: FlowNodeType) => {
      event.dataTransfer.setData("application/reactflow-nodetype", nodeType);
      event.dataTransfer.effectAllowed = "move";
    },
    [],
  );

  return (
    <div className={cn("flex w-56 flex-col gap-5 border-r bg-background/50 p-4 overflow-y-auto", className)}>
      <h3 className="text-sm font-semibold text-foreground">Nodes</h3>
      {CATEGORIES.map((cat) => {
        const items = NODE_TYPE_REGISTRY.filter((n) => n.category === cat.key);
        return (
          <div key={cat.key}>
            <div className="mb-2">
              <p className={cn("text-[11px] font-semibold uppercase tracking-wider", cat.accent)}>
                {cat.label}
              </p>
              <p className="text-[10px] text-muted-foreground">{cat.description}</p>
            </div>
            <div className="flex flex-col gap-1">
              {items.map((info) => {
                const Icon = ICON_MAP[info.icon];
                return (
                  <div
                    key={info.type}
                    draggable
                    onDragStart={(e) => onDragStart(e, info.type)}
                    className={cn(
                      "flex cursor-grab items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm transition-colors hover:bg-accent active:cursor-grabbing",
                      info.color,
                    )}
                    title={info.description}
                  >
                    {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                    <span className="truncate">{info.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
