"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Phone,
  Clock,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  Percent,
  ArrowRight,
  BarChart3,
  Frown,
  Meh,
  Smile,
} from "lucide-react";
import Link from "next/link";
import {
  AreaChart,
  Area,
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
  Legend,
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
  DateRangePicker,
  createDateRange,
  getDateRangeValues,
  type DateRange as DateRangeType,
} from "@/components/date-range-picker";
import { useCallLogs } from "@/hooks/use-calls";
import { useBots } from "@/hooks/use-bots";
import {
  useAnalyticsSummary,
  useAnalyticsTrends,
  useAnalyticsRedFlags,
  useDashboardAnalytics,
} from "@/hooks/use-analytics";
import { formatDuration, formatPhoneNumber } from "@/lib/utils";
import { TimeDisplay } from "@/components/time-display";
import type { CallLog, TrendPoint } from "@/types/api";

// -- Colors --
const VIOLET = "#8b5cf6";
const INDIGO = "#6366f1";
const EMERALD = "#10b981";
const AMBER = "#f59e0b";
const ROSE = "#f43f5e";
const SLATE = "#64748b";

const OUTCOME_COLORS: Record<string, string> = {
  success: EMERALD,
  failed: ROSE,
  "no-answer": AMBER,
  "no_answer": AMBER,
  completed: VIOLET,
  busy: SLATE,
  cancelled: SLATE,
};

const SENTIMENT_COLORS = {
  positive: EMERALD,
  neutral: AMBER,
  negative: ROSE,
};

// -- Date range helpers (now using shared DateRangePicker) --

// -- Build daily call volume from raw calls --
function buildDailyVolume(calls: CallLog[], days: number) {
  const map = new Map<string, number>();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    map.set(d.toISOString().slice(0, 10), 0);
  }
  for (const c of calls) {
    const key = c.created_at.slice(0, 10);
    if (map.has(key)) map.set(key, (map.get(key) || 0) + 1);
  }
  return Array.from(map.entries()).map(([date, count]) => ({
    date,
    label: new Date(date + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    calls: count,
  }));
}

// -- Build outcome distribution from raw calls --
function buildOutcomeDistribution(calls: CallLog[]) {
  const map = new Map<string, number>();
  for (const c of calls) {
    const key = c.status || "unknown";
    map.set(key, (map.get(key) || 0) + 1);
  }
  return Array.from(map.entries())
    .map(([name, value]) => ({
      name: name.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
      value,
      color: OUTCOME_COLORS[name] || SLATE,
    }))
    .sort((a, b) => b.value - a.value);
}

// -- Build heatmap from calls --
function buildHeatmap(calls: CallLog[]) {
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const grid: number[][] = Array.from({ length: 7 }, () =>
    Array(24).fill(0)
  );
  for (const c of calls) {
    const d = new Date(c.created_at);
    grid[d.getDay()][d.getHours()]++;
  }
  const max = Math.max(...grid.flat(), 1);
  return { grid, max, days: DAYS };
}

// -- Build funnel from calls --
function buildFunnel(calls: CallLog[]) {
  const attempted = calls.length;
  const connected = calls.filter((c) =>
    ["completed", "in-progress"].includes(c.status)
  ).length;
  const qualified = calls.filter(
    (c) =>
      c.analytics?.goal_outcome &&
      c.analytics.goal_outcome !== "unknown"
  ).length;
  const converted = calls.filter(
    (c) => c.analytics?.goal_outcome === "success"
  ).length;

  return [
    { stage: "Attempted", value: attempted, color: VIOLET, tip: "Total calls initiated in this period" },
    { stage: "Connected", value: connected, color: INDIGO, tip: "Calls with completed or in-progress status" },
    { stage: "Qualified", value: qualified, color: AMBER, tip: "Calls where a goal outcome was determined" },
    { stage: "Converted", value: converted, color: EMERALD, tip: "Calls where goal outcome was success" },
  ];
}

const FUNNEL_TIPS: Record<string, string> = {
  Attempted: "Total calls initiated in this period",
  Connected: "Calls with completed or in-progress status",
  Qualified: "Calls where a goal outcome was determined",
  Converted: "Calls where goal outcome was success",
};

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
function KPICard({
  title,
  value,
  icon: Icon,
  trend,
  trendLabel,
  gradient,
  loading,
  delay = 0,
}: {
  title: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  trend?: number;
  trendLabel?: string;
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
          <div className="min-w-0 flex-1">
            {loading ? (
              <Skeleton className="h-7 w-20" />
            ) : (
              <p className="text-2xl font-bold truncate">{value}</p>
            )}
            <div className="flex items-center gap-1.5">
              <p className="text-sm text-muted-foreground">{title}</p>
              {trend !== undefined && trend !== 0 && !loading && (
                <span
                  className={`flex items-center gap-0.5 text-xs font-medium ${
                    trend > 0 ? "text-emerald-500" : "text-rose-500"
                  }`}
                >
                  {trend > 0 ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : (
                    <TrendingDown className="h-3 w-3" />
                  )}
                  {Math.abs(trend)}%
                  {trendLabel && (
                    <span className="text-muted-foreground ml-0.5">
                      {trendLabel}
                    </span>
                  )}
                </span>
              )}
            </div>
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
      {sub && <p className="text-xs mt-1 text-muted-foreground/60">{sub}</p>}
    </div>
  );
}

// ============================================================================
// Main Dashboard Page
// ============================================================================

export default function DashboardPage() {
  const [dateRange, setDateRange] = useState<DateRangeType>(() => createDateRange("30d"));
  const [selectedBotId, setSelectedBotId] = useState<string>("all");

  const range = useMemo(() => getDateRangeValues(dateRange, 30), [dateRange]);

  const { data: bots = [], isLoading: botsLoading } = useBots();
  const { data: allCalls = [], isLoading: callsLoading } = useCallLogs(
    selectedBotId !== "all" ? { botId: selectedBotId } : undefined
  );

  // Filtered calls by date range
  const calls = useMemo(() => {
    return allCalls.filter((c) => {
      const d = c.created_at.slice(0, 10);
      return d >= range.start && d <= range.end;
    });
  }, [allCalls, range]);

  // Analytics for the selected bot — skip analytics queries when "All Bots" is selected
  // since analytics endpoints require a specific bot ID
  const analyticsBotId = selectedBotId !== "all" ? selectedBotId : "";
  const { data: summary } = useAnalyticsSummary(analyticsBotId, {
    start_date: range.start,
    end_date: range.end,
  });
  const { data: trends = [] } = useAnalyticsTrends(analyticsBotId, {
    interval: "daily",
    start_date: range.start,
    end_date: range.end,
  });
  const { data: redFlags = [] } = useAnalyticsRedFlags(analyticsBotId);

  // Use backend dashboard analytics for accurate KPIs (server-side SQL)
  const periodDays = useMemo(() => {
    const s = new Date(range.start + "T00:00:00");
    const e = new Date(range.end + "T00:00:00");
    return Math.max(1, Math.round((e.getTime() - s.getTime()) / (1000 * 60 * 60 * 24)));
  }, [range]);
  const { data: dashData } = useDashboardAnalytics({
    bot_id: selectedBotId !== "all" ? selectedBotId : undefined,
    days: periodDays,
  });

  const loading = botsLoading || callsLoading;

  // -- KPI computations (prefer backend data, fallback to client-side) --
  const kpis = useMemo(() => {
    // Use backend analytics if available
    if (dashData) {
      // Compute trend vs previous period from client-side calls
      const prevStart = new Date(range.start);
      prevStart.setDate(prevStart.getDate() - periodDays);
      const prevStartStr = prevStart.toISOString().slice(0, 10);
      const prevCalls = allCalls.filter((c) => {
        const d = c.created_at.slice(0, 10);
        return d >= prevStartStr && d < range.start;
      });
      const prevTotal = prevCalls.length;
      const callTrend =
        prevTotal > 0
          ? Math.round(((dashData.total_calls - prevTotal) / prevTotal) * 100)
          : 0;

      return {
        total: dashData.total_calls,
        connectedPct: dashData.connected_pct,
        avgDuration: dashData.avg_duration_secs ?? 0,
        conversionPct: dashData.conversion_pct,
        totalCost: dashData.total_cost,
        costPerConversion: dashData.cost_per_conversion,
        callTrend,
        successCalls: dashData.conversion_funnel?.find(s => s.stage === "Converted")?.count ?? 0,
      };
    }

    // Fallback: client-side computation from raw calls
    const total = calls.length;
    const connected = calls.filter(
      (c) => c.status === "completed" && (c.call_duration ?? 0) > 10
    ).length;
    const connectedPct = total > 0 ? Math.round((connected / total) * 100) : 0;
    const durations = calls
      .filter((c) => c.call_duration && c.call_duration > 0)
      .map((c) => c.call_duration!);
    const avgDuration =
      durations.length > 0
        ? durations.reduce((a, b) => a + b, 0) / durations.length
        : 0;

    return {
      total,
      connectedPct,
      avgDuration,
      conversionPct: 0,
      totalCost: 0,
      costPerConversion: 0,
      callTrend: 0,
      successCalls: 0,
    };
  }, [dashData, calls, allCalls, range, periodDays]);

  // -- Chart data --
  const dailyVolumeDays = useMemo(() => {
    const startDate = new Date(range.start + "T00:00:00");
    const endDate = new Date(range.end + "T00:00:00");
    return Math.max(1, Math.round((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)));
  }, [range]);

  const dailyVolume = useMemo(
    () => buildDailyVolume(calls, dailyVolumeDays),
    [calls, dailyVolumeDays]
  );

  const outcomeDistribution = useMemo(
    () => buildOutcomeDistribution(calls),
    [calls]
  );

  const heatmap = useMemo(() => buildHeatmap(calls), [calls]);

  const funnel = useMemo(() => {
    // Prefer backend funnel data when available
    if (dashData?.conversion_funnel?.length) {
      const colors = [VIOLET, INDIGO, AMBER, EMERALD];
      const tips: Record<string, string> = {
        Initiated: "Total calls initiated in this period",
        Connected: "Calls lasting > 10 seconds (real human connection)",
        Analyzed: "Calls with goal analysis completed",
        Converted: "Calls matching primary success criteria",
      };
      return dashData.conversion_funnel.map((step, i) => ({
        stage: step.stage,
        value: step.count,
        color: colors[i] || VIOLET,
        tip: tips[step.stage] || step.stage,
      }));
    }
    return buildFunnel(calls);
  }, [dashData, calls]);

  // Sentiment from call analytics
  const sentimentData = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of calls) {
      const raw = c.analytics?.sentiment || null;
      if (!raw) continue;
      const key = raw.toLowerCase();
      counts[key] = (counts[key] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([name, value]) => ({
        name: name.charAt(0).toUpperCase() + name.slice(1),
        value,
        color: SENTIMENT_COLORS[name as keyof typeof SENTIMENT_COLORS] || SLATE,
      }))
      .sort((a, b) => b.value - a.value);
  }, [calls]);

  // Top objections from red flags
  const objectionData = useMemo(() => {
    return redFlags
      .map((rf) => ({
        name: rf.flag_id.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
        count: rf.count,
        severity: rf.severity,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [redFlags]);

  // Recent calls
  const recentCalls = useMemo(
    () =>
      [...calls]
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        )
        .slice(0, 5),
    [calls]
  );

  return (
    <>
      <Header title="Dashboard" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Filters Row */}
          <div className="flex flex-wrap items-center gap-3">
            <DateRangePicker value={dateRange} onChange={setDateRange} />
            <Select value={selectedBotId} onValueChange={setSelectedBotId}>
              <SelectTrigger className="w-[240px]">
                <SelectValue placeholder="All Bots" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Bots</SelectItem>
                {bots.map((bot) => (
                  <SelectItem key={bot.id} value={bot.id}>
                    {bot.agent_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <KPICard
              title="Total Calls"
              value={kpis.total}
              icon={Phone}
              trend={kpis.callTrend}
              trendLabel="vs prev"
              gradient="from-violet-500 to-indigo-500"
              loading={loading}
              delay={0}
            />
            <KPICard
              title="Connected %"
              value={`${kpis.connectedPct}%`}
              icon={Percent}
              gradient="from-emerald-500 to-green-500"
              loading={loading}
              delay={0.08}
            />
            <KPICard
              title="Avg Duration"
              value={formatDuration(kpis.avgDuration)}
              icon={Clock}
              gradient="from-cyan-500 to-blue-500"
              loading={loading}
              delay={0.16}
            />
            <KPICard
              title="Conversion %"
              value={`${kpis.conversionPct}%`}
              icon={Target}
              gradient="from-amber-500 to-orange-500"
              loading={loading}
              delay={0.24}
            />
            <KPICard
              title="Credits Used"
              value={`₹${kpis.totalCost.toFixed(1)}`}
              icon={DollarSign}
              gradient="from-rose-500 to-pink-500"
              loading={loading}
              delay={0.32}
            />
            <KPICard
              title="Credits / Conversion"
              value={kpis.costPerConversion ? `₹${kpis.costPerConversion.toFixed(1)}` : "—"}
              icon={DollarSign}
              gradient="from-fuchsia-500 to-purple-500"
              loading={loading}
              delay={0.4}
            />
          </div>

          {/* Charts Row 1: Call Volume + Outcome Distribution */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Call Volume Over Time */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Call Volume Over Time</CardTitle>
                <CardDescription>
                  Calls per day for the selected period
                </CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-64 w-full" />
                ) : dailyVolume.length === 0 ? (
                  <EmptyState icon={BarChart3} message="No call data yet" sub="Trigger your first call to see volume trends here" />
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={dailyVolume}>
                      <defs>
                        <linearGradient
                          id="callGradient"
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="1"
                        >
                          <stop
                            offset="5%"
                            stopColor={VIOLET}
                            stopOpacity={0.3}
                          />
                          <stop
                            offset="95%"
                            stopColor={VIOLET}
                            stopOpacity={0}
                          />
                        </linearGradient>
                      </defs>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="rgba(255,255,255,0.06)"
                      />
                      <XAxis
                        dataKey="label"
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
                        dataKey="calls"
                        stroke={VIOLET}
                        strokeWidth={2}
                        fill="url(#callGradient)"
                        name="Calls"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Outcome Distribution */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Outcome Distribution</CardTitle>
                <CardDescription>Breakdown by call status</CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-64 w-full" />
                ) : outcomeDistribution.length === 0 ? (
                  <EmptyState icon={BarChart3} message="No call data yet" sub="Outcome breakdown will appear once calls complete" />
                ) : (
                  <div className="flex items-center gap-4">
                    <ResponsiveContainer width="50%" height={240}>
                      <PieChart>
                        <Pie
                          data={outcomeDistribution}
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={90}
                          paddingAngle={2}
                          dataKey="value"
                        >
                          {outcomeDistribution.map((entry, i) => (
                            <Cell key={i} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip content={<DarkTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="flex-1 space-y-2">
                      {outcomeDistribution.map((item) => (
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

          {/* Charts Row 2: Heatmap + Conversion Funnel */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Calling Heatmap */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Calling Heatmap</CardTitle>
                <CardDescription>Best call times (hour x day)</CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-48 w-full" />
                ) : calls.length === 0 ? (
                  <EmptyState icon={BarChart3} message="No call data yet" sub="Heatmap shows your best calling times by day and hour" />
                ) : (
                  <div className="overflow-x-auto">
                    <div className="min-w-[600px]">
                      {/* Hour labels */}
                      <div className="flex items-center gap-0.5 mb-1 ml-10">
                        {Array.from({ length: 24 }, (_, h) => (
                          <div
                            key={h}
                            className="flex-1 text-center text-[9px] text-muted-foreground"
                          >
                            {h % 3 === 0 ? `${h}` : ""}
                          </div>
                        ))}
                      </div>
                      {/* Grid rows */}
                      {heatmap.days.map((day, dayIdx) => (
                        <div key={day} className="flex items-center gap-0.5 mb-0.5">
                          <span className="w-10 text-xs text-muted-foreground text-right pr-2 shrink-0">
                            {day}
                          </span>
                          {heatmap.grid[dayIdx].map((count, hour) => {
                            const intensity = count / heatmap.max;
                            return (
                              <div
                                key={hour}
                                className="flex-1 aspect-square rounded-[2px] transition-colors"
                                style={{
                                  backgroundColor:
                                    count === 0
                                      ? "rgba(255,255,255,0.03)"
                                      : `rgba(139, 92, 246, ${
                                          0.15 + intensity * 0.85
                                        })`,
                                }}
                                title={`${day} ${hour}:00 - ${count} calls`}
                              />
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Conversion Funnel */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Conversion Funnel</CardTitle>
                <CardDescription>
                  Attempted to Converted progression
                </CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-48 w-full" />
                ) : calls.length === 0 ? (
                  <EmptyState icon={Target} message="No call data yet" sub="Funnel tracks your calls from attempt to conversion" />
                ) : (
                  <div className="space-y-3">
                    {funnel.map((stage) => {
                      const maxVal = funnel[0]?.value || 1;
                      const pct = maxVal > 0 ? (stage.value / maxVal) * 100 : 0;
                      return (
                        <div key={stage.stage} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span
                              className="text-muted-foreground cursor-help border-b border-dashed border-muted-foreground/40"
                              title={FUNNEL_TIPS[stage.stage]}
                            >
                              {stage.stage}
                            </span>
                            <span className="font-medium tabular-nums">{stage.value}</span>
                          </div>
                          <div className="h-6 w-full rounded bg-muted/30 overflow-hidden">
                            <div
                              className="h-full rounded transition-all duration-500"
                              style={{
                                width: `${Math.max(pct, 2)}%`,
                                backgroundColor: stage.color,
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Charts Row 3: Sentiment + Top Objections */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Sentiment Breakdown */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Sentiment Breakdown</CardTitle>
                <CardDescription>
                  Call sentiment analysis distribution
                </CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-48 w-full" />
                ) : sentimentData.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                    <div className="flex gap-3 mb-3 opacity-30">
                      <Smile className="h-8 w-8" />
                      <Meh className="h-8 w-8" />
                      <Frown className="h-8 w-8" />
                    </div>
                    <p className="text-sm">No sentiment data yet</p>
                    <p className="text-xs mt-1 text-muted-foreground/60">
                      Sentiment will appear once calls are analyzed
                    </p>
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <ResponsiveContainer width="50%" height={200}>
                      <PieChart>
                        <Pie
                          data={sentimentData}
                          cx="50%"
                          cy="50%"
                          innerRadius={45}
                          outerRadius={75}
                          paddingAngle={2}
                          dataKey="value"
                        >
                          {sentimentData.map((entry, i) => (
                            <Cell key={i} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip content={<DarkTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="flex-1 space-y-2">
                      {sentimentData.map((item) => (
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

            {/* Top Objections */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Top Objections</CardTitle>
                <CardDescription>Most common red flags detected</CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-48 w-full" />
                ) : objectionData.length === 0 ? (
                  <EmptyState
                    icon={BarChart3}
                    message="No objection data yet. Red flags will appear here once calls are analyzed."
                  />
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={objectionData} layout="vertical">
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
                        width={140}
                      />
                      <Tooltip content={<DarkTooltip />} />
                      <Bar
                        dataKey="count"
                        name="Occurrences"
                        fill={ROSE}
                        radius={[0, 4, 4, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          {/* View Detailed Analytics Link */}
          <div className="flex justify-center">
            <Button variant="outline" asChild className="gap-2">
              <Link href="/analytics">
                View Detailed Analytics
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>

          {/* Recent Calls Table */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-base">Recent Calls</CardTitle>
                <CardDescription>Latest call activity</CardDescription>
              </div>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/calls">
                  View all
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : recentCalls.length === 0 ? (
                <EmptyState icon={Phone} message="No calls yet" sub="Your recent call activity will appear here" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="py-2 text-left font-medium">Time</th>
                        <th className="py-2 text-left font-medium">Contact</th>
                        <th className="py-2 text-left font-medium">Duration</th>
                        <th className="py-2 text-left font-medium">Outcome</th>
                        <th className="py-2 text-left font-medium">Score</th>
                        <th className="py-2 text-left font-medium">Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentCalls.map((call, i) => (
                        <motion.tr
                          key={call.id}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.04 }}
                          className="border-b border-border/50 hover:bg-muted/30 transition-colors"
                        >
                          <td className="py-2.5 whitespace-nowrap text-muted-foreground">
                            <TimeDisplay date={call.created_at} />
                          </td>
                          <td className="py-2.5">
                            <div>
                              <p className="font-medium truncate max-w-[150px]">
                                {call.contact_name}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {formatPhoneNumber(call.contact_phone)}
                              </p>
                            </div>
                          </td>
                          <td className="py-2.5 whitespace-nowrap">
                            {call.call_duration
                              ? formatDuration(call.call_duration)
                              : "--"}
                          </td>
                          <td className="py-2.5">
                            <Badge
                              variant={
                                call.status === "completed"
                                  ? "secondary"
                                  : call.status === "failed"
                                  ? "destructive"
                                  : "outline"
                              }
                              className="text-xs"
                            >
                              {call.analytics?.goal_outcome?.replace(/_/g, " ") ||
                                call.status}
                            </Badge>
                          </td>
                          <td className="py-2.5 text-muted-foreground">
                            {call.analytics?.agent_word_share != null
                              ? `${Math.round(
                                  call.analytics.agent_word_share * 100
                                )}%`
                              : "--"}
                          </td>
                          <td className="py-2.5">
                            <p className="text-xs text-muted-foreground truncate max-w-[200px]">
                              {call.summary || "--"}
                            </p>
                          </td>
                        </motion.tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
