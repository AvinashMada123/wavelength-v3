"use client";

import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Users,
  CheckCircle2,
  XCircle,
  Phone,
  Clock,
  TrendingUp,
  BarChart3,
  Play,
  Pause,
  Ban,
  Loader2,
  FileEdit,
} from "lucide-react";
import { format } from "date-fns";
import { toast } from "sonner";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCampaign,
  useStartCampaign,
  usePauseCampaign,
  useCancelCampaign,
} from "@/hooks/use-campaigns";

const STATUS_CONFIG: Record<
  string,
  { label: string; className: string; icon: typeof Clock }
> = {
  draft: {
    label: "Draft",
    className: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
    icon: FileEdit,
  },
  running: {
    label: "Running",
    className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    icon: Play,
  },
  paused: {
    label: "Paused",
    className: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    icon: Pause,
  },
  completed: {
    label: "Completed",
    className: "bg-green-500/10 text-green-400 border-green-500/20",
    icon: CheckCircle2,
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
    icon: Ban,
  },
};

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  const Icon = config.icon;
  return (
    <Badge variant="outline" className={`gap-1 ${config.className}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </Badge>
  );
}

const FUNNEL_COLORS = ["#8b5cf6", "#6366f1", "#22c55e", "#f59e0b"];

export default function CampaignDetailPage() {
  const params = useParams();
  const router = useRouter();
  const campaignId = params.campaignId as string;

  const { data: campaign, isLoading, error } = useCampaign(campaignId);
  const startMutation = useStartCampaign();
  const pauseMutation = usePauseCampaign();
  const cancelMutation = useCancelCampaign();

  const actionLoading =
    startMutation.isPending ||
    pauseMutation.isPending ||
    cancelMutation.isPending;

  async function handleAction(action: "start" | "pause" | "cancel") {
    try {
      switch (action) {
        case "start":
          await startMutation.mutateAsync(campaignId);
          toast.success("Campaign started");
          break;
        case "pause":
          await pauseMutation.mutateAsync(campaignId);
          toast.success("Campaign paused");
          break;
        case "cancel":
          await cancelMutation.mutateAsync(campaignId);
          toast.success("Campaign cancelled");
          break;
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : `Failed to ${action} campaign`;
      toast.error(message);
    }
  }

  if (isLoading) {
    return (
      <>
        <Header title="Campaign Details" />
        <PageTransition>
          <div className="space-y-6 p-6">
            <Skeleton className="h-8 w-64" />
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
            <Skeleton className="h-64 w-full" />
          </div>
        </PageTransition>
      </>
    );
  }

  if (error || !campaign) {
    return (
      <>
        <Header title="Campaign Details" />
        <PageTransition>
          <div className="space-y-6 p-6">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/campaigns")}
              className="gap-1"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Campaigns
            </Button>
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <XCircle className="h-10 w-10 text-red-400 mb-3" />
                <p className="text-sm text-muted-foreground">
                  {error?.message || "Campaign not found"}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => router.push("/campaigns")}
                >
                  Back to Campaigns
                </Button>
              </CardContent>
            </Card>
          </div>
        </PageTransition>
      </>
    );
  }

  const progressPct =
    campaign.total_leads > 0
      ? Math.round((campaign.completed_leads / campaign.total_leads) * 100)
      : 0;

  const connectedPct =
    campaign.total_leads > 0
      ? Math.round(
          ((campaign.completed_leads - campaign.failed_leads) /
            campaign.total_leads) *
            100
        )
      : 0;

  // Build funnel data from lead_status_breakdown
  const breakdown = campaign.lead_status_breakdown || {};
  const funnelData = [
    { name: "Total", value: campaign.total_leads },
    {
      name: "Connected",
      value: campaign.completed_leads - campaign.failed_leads,
    },
    { name: "Qualified", value: breakdown["qualified"] || 0 },
    { name: "Converted", value: breakdown["converted"] || 0 },
  ];

  const hasFunnelData = funnelData.some((d, i) => i > 0 && d.value > 0);

  const stats = [
    {
      label: "Total Leads",
      value: campaign.total_leads,
      icon: Users,
      color: "text-violet-400",
    },
    {
      label: "Completed",
      value: campaign.completed_leads,
      icon: CheckCircle2,
      color: "text-green-400",
    },
    {
      label: "Failed",
      value: campaign.failed_leads,
      icon: XCircle,
      color: "text-red-400",
    },
    {
      label: "Connected %",
      value: `${connectedPct}%`,
      icon: Phone,
      color: "text-blue-400",
    },
    {
      label: "Concurrency",
      value: campaign.concurrency_limit,
      icon: TrendingUp,
      color: "text-amber-400",
    },
    {
      label: "Progress",
      value: `${progressPct}%`,
      icon: BarChart3,
      color: "text-indigo-400",
    },
  ];

  return (
    <>
      <Header title="Campaign Details" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Back button + Header */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push("/campaigns")}
                className="gap-1"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold tracking-tight">
                  {campaign.name}
                </h1>
                <StatusBadge status={campaign.status} />
              </div>
            </div>
            <div className="flex items-center gap-2">
              {(campaign.status === "draft" ||
                campaign.status === "paused") && (
                <Button
                  size="sm"
                  onClick={() => handleAction("start")}
                  disabled={actionLoading}
                  className="bg-gradient-to-r from-green-500 to-emerald-600 text-white hover:from-green-600 hover:to-emerald-700"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  Start
                </Button>
              )}
              {campaign.status === "running" && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleAction("pause")}
                  disabled={actionLoading}
                  className="border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/10"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Pause className="h-4 w-4" />
                  )}
                  Pause
                </Button>
              )}
              {(campaign.status === "draft" ||
                campaign.status === "running" ||
                campaign.status === "paused") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleAction("cancel")}
                  disabled={actionLoading}
                  className="border-red-500/30 text-red-400 hover:bg-red-500/10"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  Cancel
                </Button>
              )}
            </div>
          </div>

          {/* Stats cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {stats.map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <Card>
                  <CardContent className="pt-6">
                    <div className="flex items-center gap-2">
                      <stat.icon className={`h-4 w-4 ${stat.color}`} />
                      <p className="text-xs text-muted-foreground">
                        {stat.label}
                      </p>
                    </div>
                    <p className="mt-2 text-2xl font-bold">{stat.value}</p>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>

          {/* Progress bar */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-medium">Campaign Progress</p>
                <p className="text-sm text-muted-foreground">
                  {campaign.completed_leads}/{campaign.total_leads} leads (
                  {progressPct}%)
                </p>
              </div>
              <Progress value={progressPct} className="h-3" />
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                <span>
                  Created{" "}
                  {format(new Date(campaign.created_at), "MMM d, yyyy h:mm a")}
                </span>
                {campaign.started_at && (
                  <span>
                    Started{" "}
                    {format(
                      new Date(campaign.started_at),
                      "MMM d, yyyy h:mm a"
                    )}
                  </span>
                )}
                {campaign.completed_at && (
                  <span>
                    Completed{" "}
                    {format(
                      new Date(campaign.completed_at),
                      "MMM d, yyyy h:mm a"
                    )}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Lead Status Breakdown */}
          {campaign.lead_status_breakdown &&
            Object.keys(campaign.lead_status_breakdown).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Lead Status Breakdown
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(campaign.lead_status_breakdown).map(
                      ([status, count]) => (
                        <div
                          key={status}
                          className="flex items-center gap-2 rounded-lg border px-4 py-2"
                        >
                          <span className="capitalize text-sm text-muted-foreground">
                            {status.replace(/_/g, " ")}
                          </span>
                          <span className="text-lg font-semibold">{count}</span>
                        </div>
                      )
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

          {/* Conversion Funnel */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Conversion Funnel</CardTitle>
              <CardDescription>
                Lead progression through campaign stages
              </CardDescription>
            </CardHeader>
            <CardContent>
              {hasFunnelData ? (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={funnelData}
                      margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="hsl(var(--border))"
                      />
                      <XAxis
                        dataKey="name"
                        tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                      />
                      <YAxis
                        tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "hsl(var(--card))",
                          border: "1px solid hsl(var(--border))",
                          borderRadius: "8px",
                          color: "hsl(var(--foreground))",
                        }}
                      />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        {funnelData.map((_, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={FUNNEL_COLORS[index % FUNNEL_COLORS.length]}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <BarChart3 className="h-10 w-10 opacity-30 mb-3" />
                  <p className="text-sm">
                    Funnel data will appear as leads are processed
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Lead Results Table — Placeholder */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Lead Results</CardTitle>
              <CardDescription>
                Individual lead outcomes from this campaign
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Clock className="h-10 w-10 opacity-30 mb-3" />
                <p className="text-sm font-medium">
                  Detailed campaign analytics coming soon
                </p>
                <p className="text-xs mt-1">
                  Lead-by-lead results with call outcomes, scores, and
                  temperature ratings
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
