"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  BarChart3,
  Target,
  AlertTriangle,
  Shield,
  TrendingUp,
  Clock,
  Users,
  CheckCircle2,
  XCircle,
  Bell,
  BellOff,
  Eye,
  Database,
  ArrowRight,
  DollarSign,
  Thermometer,
  Zap,
  MessageSquare,
  Frown,
  Meh,
  Smile,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";

import { useBots } from "@/hooks/use-bots";
import {
  useAnalyticsSummary,
  useAnalyticsOutcomes,
  useAnalyticsRedFlags,
  useAnalyticsAlerts,
  useAnalyticsTrends,
} from "@/hooks/use-analytics";
import { useCallLogs } from "@/hooks/use-calls";
import { formatDuration, timeAgo } from "@/lib/utils";
import { acknowledgeAlert, snoozeAlert } from "@/lib/api";
import { toast } from "sonner";
import type { TrendPoint } from "@/types/api";

// -- Colors --
const VIOLET = "#8b5cf6";
const INDIGO = "#6366f1";
const EMERALD = "#10b981";
const AMBER = "#f59e0b";
const ROSE = "#f43f5e";
const CYAN = "#06b6d4";
const SLATE = "#64748b";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/10 text-red-500 border-red-500/20",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  low: "bg-blue-500/10 text-blue-500 border-blue-500/20",
};

// -- Date range --
type DateRange = "7d" | "30d" | "90d";

function getDateRange(range: DateRange): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (range) {
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "30d":
      start.setDate(start.getDate() - 30);
      break;
    case "90d":
      start.setDate(start.getDate() - 90);
      break;
  }
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

// -- Tooltip for dark theme --
function DarkTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-card px-3 py-2 shadow-xl">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-sm font-medium" style={{ color: p.color }}>
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
}

// -- KPI Card --
function StatCard({
  title,
  value,
  icon: Icon,
  gradient,
  loading,
  delay = 0,
}: {
  title: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  gradient: string;
  loading: boolean;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <Card>
        <CardContent className="flex items-center gap-4 pt-6">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${gradient} text-white shadow-lg`}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div>
            {loading ? (
              <Skeleton className="h-7 w-16" />
            ) : (
              <p className="text-2xl font-bold">{value}</p>
            )}
            <p className="text-sm text-muted-foreground">{title}</p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// -- Empty state --
function EmptyState({
  icon: Icon,
  message,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  message: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <Icon className="mb-3 h-10 w-10 opacity-30" />
      <p className="text-sm">{message}</p>
      {sub && <p className="text-xs mt-1">{sub}</p>}
    </div>
  );
}

// -- Placeholder empty state --
function PlaceholderState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <BarChart3 className="mb-3 h-10 w-10 opacity-30" />
      <p className="text-sm text-center max-w-xs">{message}</p>
    </div>
  );
}

// ============================================================================
// Main Analytics Page
// ============================================================================

export default function AnalyticsPage() {
  const router = useRouter();
  const [selectedBotId, setSelectedBotId] = useState<string>("");
  const [dateRange, setDateRange] = useState<DateRange>("30d");

  const range = useMemo(() => getDateRange(dateRange), [dateRange]);

  // Bots
  const { data: bots = [], isLoading: botsLoading } = useBots();

  // Auto-select first bot with goal_config
  const effectiveBotId = useMemo(() => {
    if (selectedBotId) return selectedBotId;
    const goalBot = bots.find((b) => b.goal_config);
    return goalBot?.id || bots[0]?.id || "";
  }, [selectedBotId, bots]);

  // Set initial bot
  useMemo(() => {
    if (!selectedBotId && effectiveBotId) {
      // Will be picked up on next render through effectiveBotId
    }
  }, [selectedBotId, effectiveBotId]);

  const selectedBot = useMemo(
    () => bots.find((b) => b.id === effectiveBotId),
    [bots, effectiveBotId]
  );

  // Analytics hooks
  const { data: summary, isLoading: summaryLoading } = useAnalyticsSummary(
    effectiveBotId,
    { start_date: range.start, end_date: range.end }
  );
  const { data: outcomes = [], isLoading: outcomesLoading } =
    useAnalyticsOutcomes(effectiveBotId, { page_size: 20 });
  const { data: redFlags = [], isLoading: redFlagsLoading } =
    useAnalyticsRedFlags(effectiveBotId);
  const { data: alerts } = useAnalyticsAlerts(effectiveBotId);
  const { data: trends = [], isLoading: trendsLoading } = useAnalyticsTrends(
    effectiveBotId,
    { interval: "daily", start_date: range.start, end_date: range.end }
  );
  const { data: calls = [] } = useCallLogs(
    effectiveBotId ? { botId: effectiveBotId } : undefined
  );

  const loading = botsLoading || summaryLoading;

  // -- Trend chart data --
  const trendChartData = useMemo(() => {
    return trends.map((t) => ({
      date: new Date(t.date + "T00:00:00").toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      total: t.total,
      red_flags: t.red_flag_count,
      ...t.outcomes,
    }));
  }, [trends]);

  // Outcome keys for line chart
  const outcomeKeys = useMemo(() => {
    const keys = new Set<string>();
    trends.forEach((t) =>
      Object.keys(t.outcomes).forEach((k) => keys.add(k))
    );
    return Array.from(keys);
  }, [trends]);

  const OUTCOME_LINE_COLORS = [EMERALD, VIOLET, AMBER, ROSE, CYAN, INDIGO];

  // -- Score distribution (from outcomes data) --
  const scoreDistribution = useMemo(() => {
    // agent_word_share as a proxy for "score" since we don't have a score field
    const ranges = [
      { label: "0-20%", min: 0, max: 0.2, count: 0 },
      { label: "20-40%", min: 0.2, max: 0.4, count: 0 },
      { label: "40-60%", min: 0.4, max: 0.6, count: 0 },
      { label: "60-80%", min: 0.6, max: 0.8, count: 0 },
      { label: "80-100%", min: 0.8, max: 1.01, count: 0 },
    ];
    for (const o of outcomes) {
      if (o.agent_word_share != null) {
        const r = ranges.find(
          (r) => o.agent_word_share! >= r.min && o.agent_word_share! < r.max
        );
        if (r) r.count++;
      }
    }
    return ranges;
  }, [outcomes]);

  // -- Objections from red flags --
  const objectionData = useMemo(() => {
    return redFlags
      .map((rf) => ({
        name: rf.flag_id
          .replace(/_/g, " ")
          .replace(/\b\w/g, (l) => l.toUpperCase()),
        count: rf.count,
        severity: rf.severity,
        color:
          rf.severity === "critical"
            ? ROSE
            : rf.severity === "high"
            ? AMBER
            : rf.severity === "medium"
            ? "#f97316"
            : CYAN,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [redFlags]);

  // Severity breakdown
  const severityBreakdown = useMemo(() => {
    const map: Record<string, number> = {};
    for (const rf of redFlags) {
      map[rf.severity] = (map[rf.severity] || 0) + rf.count;
    }
    return Object.entries(map).map(([severity, count]) => ({
      name: severity.charAt(0).toUpperCase() + severity.slice(1),
      value: count,
      color:
        severity === "critical"
          ? ROSE
          : severity === "high"
          ? AMBER
          : severity === "medium"
          ? "#f97316"
          : CYAN,
    }));
  }, [redFlags]);

  // -- Alert actions --
  const handleAcknowledge = async (analyticsId: string) => {
    try {
      await acknowledgeAlert(effectiveBotId, analyticsId, "dashboard_user");
      toast.success("Alert acknowledged");
    } catch {
      toast.error("Failed to acknowledge alert");
    }
  };

  const handleSnooze = async (analyticsId: string) => {
    const snoozeUntil = new Date(
      Date.now() + 24 * 60 * 60 * 1000
    ).toISOString();
    try {
      await snoozeAlert(effectiveBotId, analyticsId, snoozeUntil);
      toast.success("Alert snoozed for 24 hours");
    } catch {
      toast.error("Failed to snooze alert");
    }
  };

  const openCallLog = (callLogId: string | null) => {
    if (!callLogId) return;
    router.push(`/call-logs?call_id=${callLogId}`);
  };

  // -- Bot loading skeleton --
  if (botsLoading) {
    return (
      <>
        <Header title="Analytics" />
        <PageTransition>
          <div className="space-y-6 p-6">
            <Skeleton className="h-10 w-64" />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          </div>
        </PageTransition>
      </>
    );
  }

  return (
    <>
      <Header title="Analytics" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={effectiveBotId}
              onValueChange={setSelectedBotId}
            >
              <SelectTrigger className="w-[320px]">
                <SelectValue placeholder="Select a bot" />
              </SelectTrigger>
              <SelectContent>
                {bots.map((bot) => (
                  <SelectItem key={bot.id} value={bot.id}>
                    <div className="flex items-center gap-2">
                      <span>{bot.agent_name}</span>
                      <span className="text-muted-foreground">
                        ({bot.company_name})
                      </span>
                      {bot.goal_config && (
                        <Badge
                          variant="outline"
                          className="text-[10px] py-0 px-1.5"
                        >
                          Goals
                        </Badge>
                      )}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={dateRange}
              onValueChange={(v) => setDateRange(v as DateRange)}
            >
              <SelectTrigger className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7d">Last 7 days</SelectItem>
                <SelectItem value="30d">Last 30 days</SelectItem>
                <SelectItem value="90d">Last 90 days</SelectItem>
              </SelectContent>
            </Select>
            {loading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
                Loading...
              </div>
            )}
          </div>

          {/* No goal config warning */}
          {selectedBot && !selectedBot.goal_config && (
            <Card className="border-amber-500/30 bg-amber-500/5">
              <CardContent className="flex items-center gap-3 pt-6">
                <Target className="h-5 w-5 text-amber-500 shrink-0" />
                <div>
                  <p className="text-sm font-medium">
                    No Goal Configuration
                  </p>
                  <p className="text-xs text-muted-foreground">
                    This bot doesn&apos;t have goal-based analytics configured.
                    Edit the bot and add a Goal Configuration to enable outcome
                    tracking, red flag detection, and data capture.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Main Tabs */}
          <Tabs defaultValue="overview" className="space-y-4">
            <TabsList>
              <TabsTrigger value="overview" className="gap-1.5">
                <TrendingUp className="h-4 w-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="call-quality" className="gap-1.5">
                <BarChart3 className="h-4 w-4" />
                Call Quality
              </TabsTrigger>
              <TabsTrigger value="objections" className="gap-1.5">
                <AlertTriangle className="h-4 w-4" />
                Objections
                {redFlags.length > 0 && (
                  <Badge
                    variant="destructive"
                    className="ml-1 h-5 min-w-5 px-1 text-[10px]"
                  >
                    {redFlags.length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="lead-intel" className="gap-1.5">
                <Zap className="h-4 w-4" />
                Lead Intelligence
              </TabsTrigger>
              <TabsTrigger value="costs" className="gap-1.5">
                <DollarSign className="h-4 w-4" />
                Costs
              </TabsTrigger>
            </TabsList>

            {/* ============================================================ */}
            {/* TAB 1: Overview */}
            {/* ============================================================ */}
            <TabsContent value="overview" className="space-y-6">
              {/* Summary stats */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                  title="Total Analyzed"
                  value={summary?.total_analyzed ?? 0}
                  icon={BarChart3}
                  gradient="from-violet-500 to-indigo-500"
                  loading={loading}
                  delay={0}
                />
                <StatCard
                  title="Success Rate"
                  value={
                    summary?.outcomes
                      ? `${
                          summary.outcomes.find(
                            (o) => o.outcome === "success"
                          )?.percentage ?? 0
                        }%`
                      : "0%"
                  }
                  icon={CheckCircle2}
                  gradient="from-emerald-500 to-green-500"
                  loading={loading}
                  delay={0.08}
                />
                <StatCard
                  title="Avg Duration"
                  value={
                    summary?.avg_duration_secs
                      ? formatDuration(summary.avg_duration_secs)
                      : "--"
                  }
                  icon={Clock}
                  gradient="from-cyan-500 to-blue-500"
                  loading={loading}
                  delay={0.16}
                />
                <StatCard
                  title="Red Flag Rate"
                  value={`${summary?.red_flag_rate ?? 0}%`}
                  icon={AlertTriangle}
                  gradient={
                    (summary?.red_flag_rate ?? 0) > 10
                      ? "from-red-500 to-rose-500"
                      : "from-amber-500 to-orange-500"
                  }
                  loading={loading}
                  delay={0.24}
                />
              </div>

              {/* Trend charts */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Outcomes over time */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Outcomes Over Time
                    </CardTitle>
                    <CardDescription>
                      Daily outcome distribution
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {trendsLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : trendChartData.length === 0 ? (
                      <EmptyState
                        icon={BarChart3}
                        message="No trend data yet"
                      />
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <LineChart data={trendChartData}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="rgba(255,255,255,0.06)"
                          />
                          <XAxis
                            dataKey="date"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            interval="preserveStartEnd"
                          />
                          <YAxis
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            allowDecimals={false}
                          />
                          <Tooltip content={<DarkTooltip />} />
                          <Line
                            type="monotone"
                            dataKey="total"
                            stroke={VIOLET}
                            strokeWidth={2}
                            dot={false}
                            name="Total"
                          />
                          {outcomeKeys.map((key, i) => (
                            <Line
                              key={key}
                              type="monotone"
                              dataKey={key}
                              stroke={
                                OUTCOME_LINE_COLORS[
                                  i % OUTCOME_LINE_COLORS.length
                                ]
                              }
                              strokeWidth={1.5}
                              dot={false}
                              name={key
                                .replace(/_/g, " ")
                                .replace(/\b\w/g, (l) => l.toUpperCase())}
                            />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                  </CardContent>
                </Card>

                {/* Red flags over time */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Red Flags Over Time
                    </CardTitle>
                    <CardDescription>
                      Daily red flag detections
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {trendsLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : trendChartData.length === 0 ? (
                      <EmptyState
                        icon={AlertTriangle}
                        message="No red flag data yet"
                      />
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <AreaChart data={trendChartData}>
                          <defs>
                            <linearGradient
                              id="rfGradient"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="5%"
                                stopColor={ROSE}
                                stopOpacity={0.3}
                              />
                              <stop
                                offset="95%"
                                stopColor={ROSE}
                                stopOpacity={0}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="rgba(255,255,255,0.06)"
                          />
                          <XAxis
                            dataKey="date"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            interval="preserveStartEnd"
                          />
                          <YAxis
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            allowDecimals={false}
                          />
                          <Tooltip content={<DarkTooltip />} />
                          <Area
                            type="monotone"
                            dataKey="red_flags"
                            stroke={ROSE}
                            strokeWidth={2}
                            fill="url(#rfGradient)"
                            name="Red Flags"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Recent analyzed calls */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Recent Analyzed Calls
                  </CardTitle>
                  <CardDescription>
                    Latest calls with outcome analysis
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {outcomesLoading ? (
                    <div className="space-y-3">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                      ))}
                    </div>
                  ) : outcomes.length === 0 ? (
                    <EmptyState
                      icon={BarChart3}
                      message="No analyzed calls yet"
                    />
                  ) : (
                    <div className="space-y-2">
                      {outcomes.slice(0, 10).map((item, i) => (
                        <motion.div
                          key={item.id}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.03 }}
                          className="group flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-muted/50 cursor-pointer"
                          onClick={() => openCallLog(item.call_log_id)}
                        >
                          <div className="flex items-center gap-3">
                            {item.goal_outcome === "success" ? (
                              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                            ) : (
                              <XCircle className="h-4 w-4 text-muted-foreground" />
                            )}
                            <div>
                              <p className="text-sm font-medium capitalize">
                                {(item.goal_outcome || "unknown").replace(
                                  /_/g,
                                  " "
                                )}
                              </p>
                              <div className="flex items-center gap-2 mt-0.5">
                                {item.turn_count != null && (
                                  <span className="text-xs text-muted-foreground">
                                    {item.turn_count} turns
                                  </span>
                                )}
                                {item.call_duration_secs != null && (
                                  <span className="text-xs text-muted-foreground">
                                    {formatDuration(item.call_duration_secs)}
                                  </span>
                                )}
                                {item.agent_word_share != null && (
                                  <span className="text-xs text-muted-foreground">
                                    {Math.round(item.agent_word_share * 100)}%
                                    agent
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {item.has_red_flags && (
                              <Badge
                                className={
                                  SEVERITY_COLORS[
                                    item.red_flag_max_severity || "medium"
                                  ]
                                }
                              >
                                <AlertTriangle className="h-3 w-3 mr-1" />
                                {item.red_flag_max_severity}
                              </Badge>
                            )}
                            <span className="text-xs text-muted-foreground whitespace-nowrap">
                              {timeAgo(item.created_at)}
                            </span>
                            {item.call_log_id && (
                              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                            )}
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* TAB 2: Call Quality */}
            {/* ============================================================ */}
            <TabsContent value="call-quality" className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Score Distribution (agent word share as proxy) */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Talk Ratio Distribution
                    </CardTitle>
                    <CardDescription>
                      Agent word share across analyzed calls
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {outcomesLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : outcomes.length === 0 ? (
                      <PlaceholderState message="Analysis data will appear here once calls are processed" />
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={scoreDistribution}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="rgba(255,255,255,0.06)"
                          />
                          <XAxis
                            dataKey="label"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <YAxis
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            allowDecimals={false}
                          />
                          <Tooltip content={<DarkTooltip />} />
                          <Bar
                            dataKey="count"
                            name="Calls"
                            fill={VIOLET}
                            radius={[4, 4, 0, 0]}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </CardContent>
                </Card>

                {/* Sentiment Distribution */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Sentiment Distribution
                    </CardTitle>
                    <CardDescription>
                      Call sentiment analysis breakdown
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                      <div className="flex gap-3 mb-3 opacity-30">
                        <Smile className="h-8 w-8" />
                        <Meh className="h-8 w-8" />
                        <Frown className="h-8 w-8" />
                      </div>
                      <p className="text-sm text-center max-w-xs">
                        Sentiment analysis data will appear here once calls are
                        processed
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Average word share over time */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Avg Agent Word Share Over Time
                    </CardTitle>
                    <CardDescription>
                      How much the bot talks vs the lead
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {trendsLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : trendChartData.length === 0 ? (
                      <PlaceholderState message="Analysis data will appear here once calls are processed" />
                    ) : (
                      <ResponsiveContainer width="100%" height={260}>
                        <LineChart
                          data={trendChartData.map((d, i) => ({
                            ...d,
                            avgWordShare:
                              summary?.avg_agent_word_share != null
                                ? Math.round(
                                    summary.avg_agent_word_share * 100
                                  )
                                : null,
                          }))}
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="rgba(255,255,255,0.06)"
                          />
                          <XAxis
                            dataKey="date"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            interval="preserveStartEnd"
                          />
                          <YAxis
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            domain={[0, 100]}
                            unit="%"
                          />
                          <Tooltip content={<DarkTooltip />} />
                          <Line
                            type="monotone"
                            dataKey="avgWordShare"
                            stroke={CYAN}
                            strokeWidth={2}
                            dot={false}
                            name="Agent Word Share"
                            connectNulls
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    )}
                  </CardContent>
                </Card>

                {/* Score Distribution placeholder */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Call Score Distribution
                    </CardTitle>
                    <CardDescription>
                      Distribution of call quality scores
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PlaceholderState message="Call scoring data will appear here once scoring is enabled for this bot" />
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* ============================================================ */}
            {/* TAB 3: Objections */}
            {/* ============================================================ */}
            <TabsContent value="objections" className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Top Objections bar chart */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Top Objections
                    </CardTitle>
                    <CardDescription>
                      Most frequently detected red flags
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {redFlagsLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : objectionData.length === 0 ? (
                      <EmptyState
                        icon={Shield}
                        message="No objections detected yet"
                        sub="Red flags will appear here once calls are analyzed"
                      />
                    ) : (
                      <ResponsiveContainer width="100%" height={300}>
                        <BarChart
                          data={objectionData}
                          layout="vertical"
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="rgba(255,255,255,0.06)"
                            horizontal={false}
                          />
                          <XAxis
                            type="number"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            allowDecimals={false}
                          />
                          <YAxis
                            type="category"
                            dataKey="name"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            width={150}
                          />
                          <Tooltip content={<DarkTooltip />} />
                          <Bar
                            dataKey="count"
                            name="Occurrences"
                            radius={[0, 4, 4, 0]}
                          >
                            {objectionData.map((entry, i) => (
                              <Cell key={i} fill={entry.color} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </CardContent>
                </Card>

                {/* Severity breakdown */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Severity Breakdown
                    </CardTitle>
                    <CardDescription>
                      Objections by severity level
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {redFlagsLoading ? (
                      <Skeleton className="h-64 w-full" />
                    ) : severityBreakdown.length === 0 ? (
                      <EmptyState
                        icon={Shield}
                        message="No severity data yet"
                      />
                    ) : (
                      <div className="flex items-center gap-4">
                        <ResponsiveContainer width="50%" height={240}>
                          <PieChart>
                            <Pie
                              data={severityBreakdown}
                              cx="50%"
                              cy="50%"
                              innerRadius={50}
                              outerRadius={85}
                              paddingAngle={2}
                              dataKey="value"
                            >
                              {severityBreakdown.map((entry, i) => (
                                <Cell key={i} fill={entry.color} />
                              ))}
                            </Pie>
                            <Tooltip content={<DarkTooltip />} />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="flex-1 space-y-3">
                          {severityBreakdown.map((item) => (
                            <div
                              key={item.name}
                              className="flex items-center justify-between text-sm"
                            >
                              <div className="flex items-center gap-2">
                                <div
                                  className="h-3 w-3 rounded-full"
                                  style={{ backgroundColor: item.color }}
                                />
                                <span className="text-muted-foreground">
                                  {item.name}
                                </span>
                              </div>
                              <span className="font-medium">{item.value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Resolution rate placeholder */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Resolution Rate per Category
                  </CardTitle>
                  <CardDescription>
                    How well each objection type gets resolved
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {redFlagsLoading ? (
                    <Skeleton className="h-48 w-full" />
                  ) : redFlags.length === 0 ? (
                    <EmptyState
                      icon={Shield}
                      message="No objection data yet"
                    />
                  ) : (
                    <div className="space-y-3">
                      {redFlags.slice(0, 6).map((rf) => {
                        // Resolution rate is not tracked - show count with progress bar
                        const maxCount = Math.max(
                          ...redFlags.map((r) => r.count),
                          1
                        );
                        const pct = Math.round(
                          (rf.count / maxCount) * 100
                        );
                        return (
                          <div key={rf.flag_id} className="space-y-1.5">
                            <div className="flex items-center justify-between text-sm">
                              <span className="font-medium capitalize">
                                {rf.flag_id.replace(/_/g, " ")}
                              </span>
                              <div className="flex items-center gap-2">
                                <Badge
                                  className={
                                    SEVERITY_COLORS[rf.severity]
                                  }
                                >
                                  {rf.severity}
                                </Badge>
                                <span className="text-muted-foreground">
                                  {rf.count}x
                                </span>
                              </div>
                            </div>
                            <div className="h-2 rounded-full bg-muted overflow-hidden">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${pct}%` }}
                                transition={{ duration: 0.6 }}
                                className="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-500"
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* TAB 4: Lead Intelligence */}
            {/* ============================================================ */}
            <TabsContent value="lead-intel" className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Temperature Distribution */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Lead Temperature Distribution
                    </CardTitle>
                    <CardDescription>
                      Hot / Warm / Cold / Dead lead classification
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PlaceholderState message="Lead temperature data will appear here once calls are processed and leads are scored" />
                  </CardContent>
                </Card>

                {/* Qualification Rates */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Qualification Rates Over Time
                    </CardTitle>
                    <CardDescription>
                      Trends in lead qualification
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PlaceholderState message="Qualification rate trends will appear here once leads are being qualified through calls" />
                  </CardContent>
                </Card>
              </div>

              {/* Buying Signals */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Buying Signals Frequency
                  </CardTitle>
                  <CardDescription>
                    Most common buying signals detected in conversations
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <PlaceholderState message="Buying signal data will appear here once the AI starts detecting buying intent patterns in calls" />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* TAB 5: Costs */}
            {/* ============================================================ */}
            <TabsContent value="costs" className="space-y-6">
              {/* Cost summary cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                <StatCard
                  title="Total Spend"
                  value="$0.00"
                  icon={DollarSign}
                  gradient="from-violet-500 to-indigo-500"
                  loading={false}
                  delay={0}
                />
                <StatCard
                  title="Cost per Call"
                  value="$0.00"
                  icon={DollarSign}
                  gradient="from-emerald-500 to-green-500"
                  loading={false}
                  delay={0.08}
                />
                <StatCard
                  title="Cost per Conversion"
                  value="$0.00"
                  icon={DollarSign}
                  gradient="from-amber-500 to-orange-500"
                  loading={false}
                  delay={0.16}
                />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Cost per call trend */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Cost per Call Trend
                    </CardTitle>
                    <CardDescription>
                      Daily cost per call over time
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PlaceholderState message="Cost tracking will appear here once billing data is integrated with call analytics" />
                  </CardContent>
                </Card>

                {/* Cost per conversion trend */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      Cost per Conversion Trend
                    </CardTitle>
                    <CardDescription>
                      Daily cost per successful conversion
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PlaceholderState message="Conversion cost tracking will appear here once billing data is integrated" />
                  </CardContent>
                </Card>
              </div>

              {/* Cost Breakdown */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Cost Breakdown by Type
                  </CardTitle>
                  <CardDescription>
                    LLM, TTS, STT, and Telephony costs
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <PlaceholderState message="Cost breakdown by service type (LLM, TTS, STT, Telephony) will appear here once per-call cost tracking is enabled" />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </PageTransition>
    </>
  );
}
