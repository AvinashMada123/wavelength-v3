"use client";

import { formatDistanceToNow, format } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { X, Clock, AlertTriangle, CheckCircle2, MessageSquare } from "lucide-react";
import type { UseFlowJourneyReturn } from "@/hooks/use-flow-journey";

interface JourneyOverlayProps {
  journey: UseFlowJourneyReturn;
}

/**
 * Floating card that shows details about the selected lead's journey.
 * Renders as an overlay on the canvas when a lead is selected.
 */
export function JourneyOverlay({ journey }: JourneyOverlayProps) {
  if (!journey.journeyData) return null;

  const { instance, touchpoints } = journey.journeyData;

  return (
    <Card className="absolute bottom-4 left-4 z-50 w-80 shadow-xl">
      <CardContent className="p-4">
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">{instance.lead_name || "Unknown Lead"}</p>
            <p className="text-xs text-muted-foreground">{instance.lead_phone}</p>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge
              variant={instance.status === "error" ? "destructive" : "secondary"}
              className="text-xs"
            >
              {instance.status}
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0"
              onClick={journey.clearSelection}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Timeline */}
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Journey Timeline</p>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {touchpoints.map((tp, i) => {
              const isFailed = tp.status === "failed";
              const hasContent = !!tp.generated_content;

              return (
                <div
                  key={tp.id}
                  className={`flex items-start gap-2 rounded px-2 py-1.5 text-xs ${
                    isFailed ? "bg-red-50 dark:bg-red-950/30" : "bg-muted/30"
                  }`}
                >
                  {/* Icon */}
                  {isFailed ? (
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-green-500" />
                  )}

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium">{tp.node_name || tp.node_type}</span>
                      {tp.outcome && (
                        <Badge variant="outline" className="h-4 px-1 text-[10px]">
                          {tp.outcome}
                        </Badge>
                      )}
                    </div>

                    {/* Timestamp */}
                    {tp.executed_at && (
                      <div className="mt-0.5 flex items-center gap-1 text-muted-foreground">
                        <Clock className="h-2.5 w-2.5" />
                        <span>{format(new Date(tp.executed_at), "MMM d, HH:mm")}</span>
                      </div>
                    )}

                    {/* Generated content preview */}
                    {hasContent && (
                      <div className="mt-1 flex items-start gap-1 text-muted-foreground">
                        <MessageSquare className="mt-0.5 h-2.5 w-2.5 shrink-0" />
                        <span className="line-clamp-2">{tp.generated_content}</span>
                      </div>
                    )}

                    {/* Error message */}
                    {tp.error_message && (
                      <p className="mt-0.5 text-red-500">{tp.error_message}</p>
                    )}
                  </div>

                  {/* Elapsed time to next */}
                  {i < touchpoints.length - 1 && tp.completed_at && touchpoints[i + 1].scheduled_at && (
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {formatDistanceToNow(new Date(tp.completed_at), { addSuffix: false })}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Summary footer */}
        <div className="mt-3 flex items-center justify-between border-t pt-2 text-xs text-muted-foreground">
          <span>{touchpoints.length} nodes visited</span>
          {instance.started_at && (
            <span>
              Started {formatDistanceToNow(new Date(instance.started_at), { addSuffix: true })}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
