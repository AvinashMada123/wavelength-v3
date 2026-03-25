"use client";

import { useState } from "react";
import {
  MessageSquare,
  Phone,
  MessageCircle,
  Globe,
  RotateCcw,
  Loader2,
} from "lucide-react";
import { format, formatDistanceToNow, isPast } from "date-fns";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { retryTouchpoint, type SequenceTouchpoint } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const TOUCHPOINT_STATUS_CONFIG: Record<
  string,
  { label: string; className: string; strikethrough?: boolean }
> = {
  pending: {
    label: "Pending",
    className: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  },
  generating: {
    label: "Generating",
    className: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  },
  sent: {
    label: "Sent",
    className: "bg-green-500/10 text-green-400 border-green-500/20",
  },
  failed: {
    label: "Failed",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
  },
  awaiting_reply: {
    label: "Awaiting Reply",
    className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  },
  replied: {
    label: "Replied",
    className: "bg-green-500/10 text-green-400 border-green-500/20",
  },
  skipped: {
    label: "Skipped",
    className: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
    strikethrough: true,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ChannelIcon({ channel }: { channel: string }) {
  if (channel === "whatsapp_template" || channel === "whatsapp_session") {
    return <MessageSquare className="h-4 w-4 shrink-0" />;
  }
  if (channel === "voice_call") {
    return <Phone className="h-4 w-4 shrink-0" />;
  }
  if (channel === "webhook") {
    return <Globe className="h-4 w-4 shrink-0" />;
  }
  // sms and fallback
  return <MessageCircle className="h-4 w-4 shrink-0" />;
}

function StatusBadge({ status }: { status: string }) {
  const config =
    TOUCHPOINT_STATUS_CONFIG[status] ?? TOUCHPOINT_STATUS_CONFIG.pending;
  return (
    <Badge
      variant="outline"
      className={`text-xs ${config.className} ${config.strikethrough ? "line-through" : ""}`}
    >
      {config.label}
    </Badge>
  );
}

function RelativeCountdown({ scheduledAt }: { scheduledAt: string }) {
  const date = new Date(scheduledAt);
  if (isPast(date)) {
    return (
      <span className="text-xs text-muted-foreground">
        {formatDistanceToNow(date, { addSuffix: true })}
      </span>
    );
  }
  return (
    <span className="text-xs text-muted-foreground">
      in {formatDistanceToNow(date)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Single card
// ---------------------------------------------------------------------------

function TouchpointCard({ touchpoint }: { touchpoint: SequenceTouchpoint }) {
  const [retrying, setRetrying] = useState(false);

  const stepName =
    (touchpoint.step_snapshot?.name as string | undefined) ??
    `Step ${touchpoint.step_order}`;
  const channel =
    (touchpoint.step_snapshot?.channel as string | undefined) ?? "";

  async function handleRetry() {
    setRetrying(true);
    try {
      await retryTouchpoint(touchpoint.id);
      toast.success("Touchpoint queued for retry");
    } catch {
      toast.error("Failed to retry touchpoint");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="rounded-lg border bg-card p-3 space-y-2 text-sm">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-muted-foreground">
            <ChannelIcon channel={channel} />
          </span>
          <span className="font-medium truncate">{stepName}</span>
        </div>
        <StatusBadge status={touchpoint.status} />
      </div>

      {/* Scheduled at */}
      <div className="text-xs text-muted-foreground">
        Scheduled:{" "}
        {format(new Date(touchpoint.scheduled_at), "MMM d, yyyy HH:mm")}
      </div>

      {/* Expanded details by status */}
      {touchpoint.status === "pending" && (
        <RelativeCountdown scheduledAt={touchpoint.scheduled_at} />
      )}

      {(touchpoint.status === "sent" ||
        touchpoint.status === "awaiting_reply") && (
        <div className="space-y-1">
          {touchpoint.generated_content && (
            <p className="text-xs text-muted-foreground line-clamp-3 break-words">
              {touchpoint.generated_content.length > 200
                ? touchpoint.generated_content.slice(0, 200) + "…"
                : touchpoint.generated_content}
            </p>
          )}
          {touchpoint.sent_at && (
            <p className="text-xs text-muted-foreground">
              Sent:{" "}
              {format(new Date(touchpoint.sent_at), "MMM d, yyyy HH:mm")}
            </p>
          )}
        </div>
      )}

      {touchpoint.status === "replied" && (
        <div className="space-y-1">
          {touchpoint.reply_text && (
            <div className="rounded bg-muted/50 px-2 py-1">
              <p className="text-xs text-foreground">{touchpoint.reply_text}</p>
            </div>
          )}
          {touchpoint.reply_response && (
            <p className="text-xs text-muted-foreground">
              {touchpoint.reply_response}
            </p>
          )}
        </div>
      )}

      {touchpoint.status === "failed" && (
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs text-red-400 break-words flex-1">
            {touchpoint.error_message ?? "Unknown error"}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="h-6 text-xs shrink-0"
            onClick={handleRetry}
            disabled={retrying}
          >
            {retrying ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <>
                <RotateCcw className="h-3 w-3" />
                Retry
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

interface TouchpointTimelineProps {
  touchpoints: SequenceTouchpoint[];
}

export function TouchpointTimeline({ touchpoints }: TouchpointTimelineProps) {
  if (touchpoints.length === 0) {
    return (
      <p className="py-4 text-center text-xs text-muted-foreground">
        No touchpoints yet.
      </p>
    );
  }

  const sorted = [...touchpoints].sort(
    (a, b) => a.step_order - b.step_order
  );

  return (
    <div className="relative pl-4">
      {/* Vertical connecting line */}
      <div className="absolute left-[7px] top-3 bottom-3 w-px bg-border" />

      <div className="space-y-3">
        {sorted.map((tp, idx) => (
          <div key={tp.id} className="relative flex items-start gap-3">
            {/* Dot */}
            <div
              className={`relative z-10 mt-3 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${
                tp.status === "sent" || tp.status === "replied"
                  ? "border-green-500 bg-green-500/20"
                  : tp.status === "failed"
                    ? "border-red-500 bg-red-500/20"
                    : tp.status === "awaiting_reply"
                      ? "border-blue-500 bg-blue-500/20"
                      : tp.status === "generating"
                        ? "border-yellow-500 bg-yellow-500/20"
                        : tp.status === "skipped"
                          ? "border-zinc-500 bg-zinc-500/20"
                          : "border-zinc-600 bg-background"
              }`}
            />

            {/* Card */}
            <div className="flex-1 min-w-0">
              <TouchpointCard touchpoint={tp} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
