"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import { format } from "date-fns";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import type { FunnelData, FailuresData, LeadDetail } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AnalyticsDrillDownProps {
  type: "template" | "lead";
  onBack: () => void;
  // Template mode
  funnelData?: FunnelData | null;
  failuresData?: FailuresData | null;
  // Lead mode
  leadDetail?: LeadDetail | null;
}

// ---------------------------------------------------------------------------
// Badge config
// ---------------------------------------------------------------------------

const TIER_CONFIG: Record<string, { label: string; className: string }> = {
  hot: { label: "Hot", className: "bg-green-500/20 text-green-400" },
  warm: { label: "Warm", className: "bg-yellow-500/20 text-yellow-400" },
  cold: { label: "Cold", className: "bg-blue-500/20 text-blue-400" },
  inactive: { label: "Inactive", className: "bg-gray-500/20 text-gray-400" },
};

const CHANNEL_CONFIG: Record<string, { label: string; className: string }> = {
  whatsapp_template: { label: "WhatsApp Template", className: "bg-green-500/20 text-green-400" },
  whatsapp_session: { label: "WhatsApp Session", className: "bg-emerald-500/20 text-emerald-400" },
  sms: { label: "SMS", className: "bg-blue-500/20 text-blue-400" },
  voice_call: { label: "Voice Call", className: "bg-purple-500/20 text-purple-400" },
  webhook: { label: "Webhook", className: "bg-orange-500/20 text-orange-400" },
};

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  sent: { label: "Sent", className: "bg-blue-500/20 text-blue-400" },
  replied: { label: "Replied", className: "bg-green-500/20 text-green-400" },
  failed: { label: "Failed", className: "bg-red-500/20 text-red-400" },
  skipped: { label: "Skipped", className: "bg-yellow-500/20 text-yellow-400" },
};

// ---------------------------------------------------------------------------
// Template drill-down
// ---------------------------------------------------------------------------

function TemplateDrillDown({
  funnelData,
  failuresData,
}: {
  funnelData: FunnelData | null | undefined;
  failuresData: FailuresData | null | undefined;
}) {
  if (!funnelData) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const maxSent = funnelData.steps.length > 0 ? Math.max(funnelData.steps[0].sent, 1) : 1;

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Total Entered
            </p>
            <p className="text-2xl font-bold mt-1">
              {funnelData.total_entered.toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Steps
            </p>
            <p className="text-2xl font-bold mt-1">
              {funnelData.steps.length}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Step Funnel */}
      <Card>
        <CardContent className="p-4">
          <p className="text-sm font-medium mb-4">Step Funnel</p>
          {funnelData.steps.length === 0 ? (
            <p className="text-sm text-muted-foreground">No steps to display</p>
          ) : (
            <div className="space-y-3">
              {funnelData.steps.map((step) => {
                const widthPercent = Math.max((step.sent / maxSent) * 100, 2);
                return (
                  <div key={step.step_order} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium truncate mr-2">
                        {step.step_order}. {step.name}
                      </span>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {step.sent} sent
                        {step.skipped > 0 && <> &middot; {step.skipped} skipped</>}
                        {step.failed > 0 && <> &middot; {step.failed} failed</>}
                        {step.replied > 0 && <> &middot; {step.replied} replied</>}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full bg-violet-500 rounded-full transition-all"
                          style={{ width: `${widthPercent}%` }}
                        />
                      </div>
                      {step.drop_off_rate > 0 && (
                        <span className="text-xs text-red-400 whitespace-nowrap">
                          -{(step.drop_off_rate * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Failure Reasons */}
      {failuresData && failuresData.total_failed > 0 && (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm font-medium mb-3">Failure Reasons</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reason</TableHead>
                  <TableHead className="text-right">Count</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {failuresData.reasons.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell>{r.reason}</TableCell>
                    <TableCell className="text-right">{r.count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="mt-4 flex items-center gap-4 text-sm text-muted-foreground">
              <span>
                Retried: {failuresData.retry_stats.total_retried}
              </span>
              <span>
                Retry success rate:{" "}
                {(failuresData.retry_stats.retry_success_rate * 100).toFixed(1)}%
              </span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lead drill-down
// ---------------------------------------------------------------------------

function LeadDrillDown({ leadDetail }: { leadDetail: LeadDetail | null | undefined }) {
  if (!leadDetail) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const tierConfig = TIER_CONFIG[leadDetail.tier] ?? TIER_CONFIG.inactive;

  const scoreCategories = [
    { label: "Activity", ...leadDetail.score_breakdown.activity },
    { label: "Recency", ...leadDetail.score_breakdown.recency },
    { label: "Outcome", ...leadDetail.score_breakdown.outcome },
  ];

  return (
    <div className="space-y-6">
      {/* Score Breakdown */}
      <Card>
        <CardContent className="p-4">
          <p className="text-sm font-medium mb-4">Score Breakdown</p>
          <div className="space-y-3">
            {scoreCategories.map((cat) => (
              <div key={cat.label} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span>{cat.label}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {cat.score}/{cat.max}
                  </span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-violet-500 rounded-full transition-all"
                    style={{ width: `${cat.max > 0 ? (cat.score / cat.max) * 100 : 0}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Active Sequences
            </p>
            <p className="text-2xl font-bold mt-1">
              {leadDetail.active_sequences}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Total Replies
            </p>
            <p className="text-2xl font-bold mt-1">
              {leadDetail.total_replies}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              Avg Reply Time
            </p>
            <p className="text-2xl font-bold mt-1">
              {leadDetail.avg_reply_time_hours !== null
                ? `${leadDetail.avg_reply_time_hours}h`
                : "\u2014"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Engagement Timeline */}
      <Card>
        <CardContent className="p-4">
          <p className="text-sm font-medium mb-4">Engagement Timeline</p>
          {leadDetail.timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">No interactions yet</p>
          ) : (
            <div className="relative pl-6 border-l-2 border-border space-y-6">
              {leadDetail.timeline.map((entry, i) => {
                const channelCfg = CHANNEL_CONFIG[entry.channel] ?? {
                  label: entry.channel,
                  className: "bg-gray-500/20 text-gray-400",
                };
                const statusCfg = STATUS_CONFIG[entry.status] ?? {
                  label: entry.status,
                  className: "bg-gray-500/20 text-gray-400",
                };

                return (
                  <div key={i} className="relative">
                    {/* Timeline dot */}
                    <div className="absolute -left-[calc(1.5rem+5px)] top-1.5 h-2.5 w-2.5 rounded-full bg-violet-500 ring-2 ring-background" />

                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">
                        {format(new Date(entry.timestamp), "MMM d, yyyy h:mm a")}
                      </p>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium">
                          {entry.template_name}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {entry.step_name}
                        </span>
                        <Badge className={channelCfg.className}>
                          {channelCfg.label}
                        </Badge>
                        <Badge className={statusCfg.className}>
                          {statusCfg.label}
                        </Badge>
                      </div>
                      {entry.content_preview && (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {entry.content_preview}
                        </p>
                      )}
                      {entry.reply_text && (
                        <div className="mt-1 pl-3 border-l-2 border-green-500/30">
                          <p className="text-sm text-green-400">
                            {entry.reply_text}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AnalyticsDrillDown({
  type,
  onBack,
  funnelData,
  failuresData,
  leadDetail,
}: AnalyticsDrillDownProps) {
  // Header content based on mode
  const title =
    type === "template"
      ? funnelData?.template_name ?? "Loading..."
      : leadDetail
        ? (leadDetail.lead_name ?? "Unknown Lead")
        : "Loading...";

  const tierConfig =
    type === "lead" && leadDetail
      ? TIER_CONFIG[leadDetail.tier] ?? TIER_CONFIG.inactive
      : null;

  return (
    <div className="space-y-6">
      {/* Back + Title */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back
        </Button>
        <h2 className="text-lg font-semibold">{title}</h2>
        {type === "lead" && leadDetail && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground tabular-nums">
              {leadDetail.score}
            </span>
            {tierConfig && (
              <Badge className={tierConfig.className}>{tierConfig.label}</Badge>
            )}
          </div>
        )}
      </div>

      {/* Content */}
      {type === "template" ? (
        <TemplateDrillDown funnelData={funnelData} failuresData={failuresData} />
      ) : (
        <LeadDrillDown leadDetail={leadDetail} />
      )}
    </div>
  );
}
