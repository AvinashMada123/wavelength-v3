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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NODE_TYPE_REGISTRY, type FlowNodeType } from "@/lib/flow-types";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Phone, MessageSquare, MessageCircle, Sparkles, GitBranch, Clock, Bell, Target, CircleStop,
};

const CATEGORIES = [
  { key: "action" as const, label: "Actions" },
  { key: "control" as const, label: "Control" },
  { key: "terminal" as const, label: "Terminal" },
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
    <div className={cn("flex w-56 flex-col gap-4 border-r bg-background p-4", className)}>
      <h3 className="text-sm font-semibold text-foreground">Nodes</h3>
      {CATEGORIES.map((cat) => {
        const items = NODE_TYPE_REGISTRY.filter((n) => n.category === cat.key);
        return (
          <div key={cat.key}>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {cat.label}
            </p>
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
