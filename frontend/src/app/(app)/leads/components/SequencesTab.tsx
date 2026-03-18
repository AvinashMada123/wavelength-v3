"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  PauseCircle,
  Layers,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchInstances, fetchInstance } from "@/lib/sequences-api";
import type { SequenceInstance, SequenceTouchpoint } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const INSTANCE_STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500/15 text-green-400 border-green-500/25",
  paused: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  completed: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  cancelled: "bg-red-500/15 text-red-400 border-red-500/25",
  failed: "bg-red-500/15 text-red-400 border-red-500/25",
};

const TOUCHPOINT_STATUS_COLORS: Record<string, string> = {
  pending: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
  scheduled: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  sent: "bg-green-500/15 text-green-400 border-green-500/25",
  delivered: "bg-green-500/15 text-green-400 border-green-500/25",
  failed: "bg-red-500/15 text-red-400 border-red-500/25",
  skipped: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
};

function instanceStatusIcon(status: string) {
  switch (status) {
    case "active":
      return <Activity className="h-3.5 w-3.5" />;
    case "completed":
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case "paused":
      return <PauseCircle className="h-3.5 w-3.5" />;
    case "cancelled":
    case "failed":
      return <XCircle className="h-3.5 w-3.5" />;
    default:
      return <Clock className="h-3.5 w-3.5" />;
  }
}

// ---------------------------------------------------------------------------
// TouchpointTimeline
// ---------------------------------------------------------------------------

function TouchpointTimeline({ touchpoints }: { touchpoints: SequenceTouchpoint[] }) {
  if (!touchpoints || touchpoints.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-3 pl-2">
        No touchpoints recorded yet.
      </p>
    );
  }

  const sorted = [...touchpoints].sort((a, b) => a.step_order - b.step_order);

  return (
    <div className="mt-3 space-y-0 pl-1">
      {sorted.map((tp, i) => (
        <div key={tp.id} className="relative pl-5 pb-4 last:pb-0">
          {/* Vertical line */}
          {i < sorted.length - 1 && (
            <div className="absolute left-[7px] top-3 bottom-0 w-px bg-border" />
          )}
          {/* Dot */}
          <div
            className={`absolute left-0 top-1.5 h-3.5 w-3.5 rounded-full border-2 bg-background ${
              tp.status === "sent" || tp.status === "delivered"
                ? "border-green-500"
                : tp.status === "failed"
                ? "border-red-500"
                : tp.status === "skipped"
                ? "border-zinc-500"
                : "border-yellow-500"
            }`}
          />

          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium">
                Step {tp.step_order + 1}
                {tp.step_snapshot?.name ? ` — ${tp.step_snapshot.name}` : ""}
              </span>
              <Badge
                variant="outline"
                className={`text-[10px] px-1.5 py-0 ${
                  TOUCHPOINT_STATUS_COLORS[tp.status] ??
                  "bg-zinc-500/15 text-zinc-400 border-zinc-500/25"
                }`}
              >
                {tp.status}
              </Badge>
              {tp.step_snapshot?.channel && (
                <Badge
                  variant="outline"
                  className="text-[10px] px-1.5 py-0 bg-violet-500/10 text-violet-400 border-violet-500/25"
                >
                  {tp.step_snapshot.channel}
                </Badge>
              )}
            </div>

            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
              {tp.scheduled_at && (
                <span className="flex items-center gap-1">
                  <CalendarDays className="h-3 w-3" />
                  {format(new Date(tp.scheduled_at), "MMM d, h:mm a")}
                </span>
              )}
              {tp.sent_at && (
                <span className="text-green-400/80">
                  Sent {format(new Date(tp.sent_at), "MMM d, h:mm a")}
                </span>
              )}
            </div>

            {tp.generated_content && (
              <p className="text-xs text-muted-foreground bg-muted/40 rounded p-2 mt-1 line-clamp-2">
                {tp.generated_content}
              </p>
            )}
            {tp.error_message && (
              <p className="text-xs text-red-400 mt-1">{tp.error_message}</p>
            )}
            {tp.reply_text && (
              <div className="text-xs bg-muted/40 rounded p-2 mt-1 space-y-0.5">
                <span className="text-muted-foreground font-medium">Reply: </span>
                <span className="text-foreground/80">{tp.reply_text}</span>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Instance card (expandable)
// ---------------------------------------------------------------------------

function InstanceCard({ instance }: { instance: SequenceInstance }) {
  const [expanded, setExpanded] = useState(false);

  const { data: fullInstance, isLoading: loadingDetail } = useQuery({
    queryKey: ["sequence-instance", instance.id],
    queryFn: () => fetchInstance(instance.id),
    enabled: expanded,
    staleTime: 30_000,
  });

  const stepCount =
    fullInstance?.touchpoints?.length ?? instance.current_step ?? 0;
  const totalSteps = fullInstance?.touchpoints?.length ?? null;

  return (
    <Card
      className={`transition-colors ${
        expanded ? "border-violet-500/30" : "hover:border-violet-500/20"
      }`}
    >
      <CardContent className="p-4">
        {/* Header row */}
        <button
          className="w-full text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1 min-w-0">
              <p className="text-sm font-medium truncate">
                {instance.template_name ?? "Sequence"}
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge
                  variant="outline"
                  className={`text-xs gap-1 ${
                    INSTANCE_STATUS_COLORS[instance.status] ??
                    "text-muted-foreground"
                  }`}
                >
                  {instanceStatusIcon(instance.status)}
                  {instance.status}
                </Badge>
                {instance.started_at && (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <CalendarDays className="h-3 w-3" />
                    Started {format(new Date(instance.started_at), "MMM d, yyyy")}
                  </span>
                )}
                {totalSteps !== null && (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Layers className="h-3 w-3" />
                    {stepCount} / {totalSteps} steps
                  </span>
                )}
              </div>
            </div>
            <div className="shrink-0 text-muted-foreground pt-0.5">
              {expanded ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </div>
          </div>
        </button>

        {/* Expanded: touchpoint timeline */}
        {expanded && (
          <div className="mt-3 border-t pt-3">
            {loadingDetail ? (
              <div className="space-y-3 pl-5">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : (
              <TouchpointTimeline
                touchpoints={fullInstance?.touchpoints ?? []}
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// SequencesTab
// ---------------------------------------------------------------------------

export function SequencesTab({ leadId }: { leadId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["lead-sequences", leadId],
    queryFn: () => fetchInstances({ lead_id: leadId }),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <XCircle className="h-8 w-8 opacity-40 mb-2" />
        <p className="text-sm">Failed to load sequences</p>
      </div>
    );
  }

  const instances = data?.items ?? [];

  if (instances.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Activity className="h-10 w-10 opacity-25 mb-3" />
        <p className="text-sm font-medium">No engagement sequences for this lead</p>
        <p className="text-xs mt-1">
          Sequences will appear here once triggered for this lead.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {instances.map((instance) => (
        <InstanceCard key={instance.id} instance={instance} />
      ))}
    </div>
  );
}
