"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
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
  ChevronDown,
  Database,
  ArrowRight,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";

import {
  fetchBots,
  fetchAnalyticsSummary,
  fetchAnalyticsOutcomes,
  fetchAnalyticsRedFlags,
  fetchAnalyticsAlerts,
  fetchAnalyticsTrends,
  fetchAnalyticsCapturedData,
  acknowledgeAlert,
  snoozeAlert,
} from "@/lib/api";
import { formatDuration, formatDate, timeAgo } from "@/lib/utils";
import type {
  BotConfig,
  AnalyticsSummaryResponse,
  AnalyticsOutcomeItem,
  RedFlagGroupItem,
  AlertsResponse,
  TrendPoint,
  CapturedDataFieldSummary,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/10 text-red-500 border-red-500/20",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  low: "bg-blue-500/10 text-blue-500 border-blue-500/20",
};

const OUTCOME_COLORS = [
  "from-emerald-500 to-green-500",
  "from-violet-500 to-indigo-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-cyan-500 to-blue-500",
  "from-fuchsia-500 to-purple-500",
];

function getSeverityIcon(severity: string) {
  if (severity === "critical" || severity === "high") return AlertTriangle;
  return Shield;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AnalyticsPage() {
  const router = useRouter();
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);

  // Analytics data
  const [summary, setSummary] = useState<AnalyticsSummaryResponse | null>(null);
  const [outcomes, setOutcomes] = useState<AnalyticsOutcomeItem[]>([]);
  const [redFlags, setRedFlags] = useState<RedFlagGroupItem[]>([]);
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [capturedData, setCapturedData] = useState<CapturedDataFieldSummary[]>([]);

  // Load bots
  useEffect(() => {
    fetchBots()
      .then((b) => {
        setBots(b);
        // Auto-select first bot with goal_config
        const goalBot = b.find((bot) => bot.goal_config);
        if (goalBot) setSelectedBotId(goalBot.id);
        else if (b.length > 0) setSelectedBotId(b[0].id);
      })
      .catch(() => toast.error("Failed to load bots"))
      .finally(() => setLoading(false));
  }, []);

  // Load analytics when bot changes
  const loadAnalytics = useCallback(async (botId: string) => {
    if (!botId) return;
    setDataLoading(true);
    try {
      const [s, o, rf, al, tr, cd] = await Promise.all([
        fetchAnalyticsSummary(botId),
        fetchAnalyticsOutcomes(botId, { page_size: 20 }),
        fetchAnalyticsRedFlags(botId),
        fetchAnalyticsAlerts(botId),
        fetchAnalyticsTrends(botId, { interval: "daily" }),
        fetchAnalyticsCapturedData(botId),
      ]);
      setSummary(s);
      setOutcomes(o);
      setRedFlags(rf);
      setAlerts(al);
      setTrends(tr);
      setCapturedData(cd);
    } catch {
      toast.error("Failed to load analytics");
    } finally {
      setDataLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedBotId) loadAnalytics(selectedBotId);
  }, [selectedBotId, loadAnalytics]);

  const selectedBot = useMemo(
    () => bots.find((b) => b.id === selectedBotId),
    [bots, selectedBotId]
  );

  const hasGoalConfig = selectedBot?.goal_config != null;

  // Alert actions
  const handleAcknowledge = async (analyticsId: string) => {
    try {
      await acknowledgeAlert(selectedBotId, analyticsId, "dashboard_user");
      toast.success("Alert acknowledged");
      loadAnalytics(selectedBotId);
    } catch {
      toast.error("Failed to acknowledge alert");
    }
  };

  const handleSnooze = async (analyticsId: string) => {
    const snoozeUntil = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
    try {
      await snoozeAlert(selectedBotId, analyticsId, snoozeUntil);
      toast.success("Alert snoozed for 24 hours");
      loadAnalytics(selectedBotId);
    } catch {
      toast.error("Failed to snooze alert");
    }
  };

  // Navigate to call log detail
  const openCallLog = (callLogId: string | null) => {
    if (!callLogId) return;
    router.push(`/call-logs?call_id=${callLogId}`);
  };

  // Trends chart
  const maxTrendTotal = Math.max(...trends.map((t) => t.total), 1);

  if (loading) {
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
          {/* Bot Selector */}
          <div className="flex items-center gap-4">
            <Select value={selectedBotId} onValueChange={setSelectedBotId}>
              <SelectTrigger className="w-[320px]">
                <SelectValue placeholder="Select a bot" />
              </SelectTrigger>
              <SelectContent>
                {bots.map((bot) => (
                  <SelectItem key={bot.id} value={bot.id}>
                    <div className="flex items-center gap-2">
                      <span>{bot.agent_name}</span>
                      <span className="text-muted-foreground">({bot.company_name})</span>
                      {bot.goal_config && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1.5">
                          Goals
                        </Badge>
                      )}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {dataLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
                Loading...
              </div>
            )}
          </div>

          {!hasGoalConfig && selectedBot && (
            <Card className="border-amber-500/30 bg-amber-500/5">
              <CardContent className="flex items-center gap-3 pt-6">
                <Target className="h-5 w-5 text-amber-500 shrink-0" />
                <div>
                  <p className="text-sm font-medium">No Goal Configuration</p>
                  <p className="text-xs text-muted-foreground">
                    This bot doesn&apos;t have goal-based analytics configured. Edit the bot and add a Goal Configuration to enable outcome tracking, red flag detection, and data capture.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {summary && (
            <>
              {/* Stats Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                  {
                    title: "Total Analyzed",
                    value: summary.total_analyzed,
                    icon: BarChart3,
                    gradient: "from-violet-500 to-indigo-500",
                  },
                  {
                    title: "Avg Duration",
                    value: summary.avg_duration_secs
                      ? formatDuration(summary.avg_duration_secs)
                      : "--",
                    icon: Clock,
                    gradient: "from-emerald-500 to-green-500",
                  },
                  {
                    title: "Red Flag Rate",
                    value: `${summary.red_flag_rate}%`,
                    icon: AlertTriangle,
                    gradient: summary.red_flag_rate > 10
                      ? "from-red-500 to-rose-500"
                      : "from-amber-500 to-orange-500",
                  },
                  {
                    title: "Avg Word Share",
                    value: summary.avg_agent_word_share
                      ? `${Math.round(summary.avg_agent_word_share * 100)}%`
                      : "--",
                    icon: Users,
                    gradient: "from-cyan-500 to-blue-500",
                  },
                ].map((stat, i) => (
                  <motion.div
                    key={stat.title}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}
                  >
                    <Card>
                      <CardContent className="flex items-center gap-4 pt-6">
                        <div
                          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${stat.gradient} text-white shadow-lg`}
                        >
                          <stat.icon className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="text-2xl font-bold">{stat.value}</p>
                          <p className="text-sm text-muted-foreground">{stat.title}</p>
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                ))}
              </div>

              {/* Tabs: Overview, Alerts, Red Flags, Captured Data */}
              <Tabs defaultValue="overview" className="space-y-4">
                <TabsList>
                  <TabsTrigger value="overview" className="gap-1.5">
                    <TrendingUp className="h-4 w-4" />
                    Overview
                  </TabsTrigger>
                  <TabsTrigger value="alerts" className="gap-1.5">
                    <Bell className="h-4 w-4" />
                    Alerts
                    {alerts && alerts.total_unacknowledged > 0 && (
                      <Badge
                        variant="destructive"
                        className="ml-1 h-5 min-w-5 px-1 text-[10px]"
                      >
                        {alerts.total_unacknowledged}
                      </Badge>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="red-flags" className="gap-1.5">
                    <AlertTriangle className="h-4 w-4" />
                    Red Flags
                  </TabsTrigger>
                  <TabsTrigger value="captured-data" className="gap-1.5">
                    <Database className="h-4 w-4" />
                    Captured Data
                  </TabsTrigger>
                </TabsList>

                {/* --- Overview Tab --- */}
                <TabsContent value="overview" className="space-y-6">
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Outcome Breakdown */}
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Goal Outcomes</CardTitle>
                        <CardDescription>Distribution of call outcomes</CardDescription>
                      </CardHeader>
                      <CardContent>
                        {summary.outcomes.length === 0 ? (
                          <p className="text-sm text-muted-foreground py-8 text-center">
                            No analyzed calls yet
                          </p>
                        ) : (
                          <div className="space-y-3">
                            {summary.outcomes.map((o, i) => (
                              <div key={o.outcome} className="space-y-1.5">
                                <div className="flex items-center justify-between text-sm">
                                  <span className="font-medium capitalize">
                                    {o.outcome.replace(/_/g, " ")}
                                  </span>
                                  <span className="text-muted-foreground">
                                    {o.count} ({o.percentage}%)
                                  </span>
                                </div>
                                <div className="h-2 rounded-full bg-muted overflow-hidden">
                                  <motion.div
                                    initial={{ width: 0 }}
                                    animate={{ width: `${o.percentage}%` }}
                                    transition={{ delay: i * 0.1, duration: 0.6 }}
                                    className={`h-full rounded-full bg-gradient-to-r ${OUTCOME_COLORS[i % OUTCOME_COLORS.length]}`}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>

                    {/* Trends Chart */}
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Daily Trends</CardTitle>
                        <CardDescription>Calls analyzed per day</CardDescription>
                      </CardHeader>
                      <CardContent>
                        {trends.length === 0 ? (
                          <p className="text-sm text-muted-foreground py-8 text-center">
                            No trend data yet
                          </p>
                        ) : (
                          <div className="flex h-48 items-end justify-between gap-1.5">
                            {trends.slice(-14).map((day, i) => {
                              const barHeight = maxTrendTotal > 0
                                ? Math.max((day.total / maxTrendTotal) * 148, day.total > 0 ? 8 : 4)
                                : 4;
                              const hasFlags = day.red_flag_count > 0;
                              return (
                                <div
                                  key={day.date}
                                  className="group flex flex-1 flex-col items-center gap-1"
                                >
                                  <span className="text-[10px] font-medium text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                                    {day.total > 0 ? day.total : ""}
                                    {hasFlags && (
                                      <span className="text-red-400 ml-0.5">
                                        !{day.red_flag_count}
                                      </span>
                                    )}
                                  </span>
                                  <motion.div
                                    initial={{ height: 0 }}
                                    animate={{ height: barHeight }}
                                    transition={{ delay: i * 0.04, duration: 0.6 }}
                                    className={`w-full max-w-[32px] rounded-t-sm ${
                                      hasFlags
                                        ? "bg-gradient-to-t from-red-500 to-orange-400"
                                        : day.total > 0
                                        ? "bg-gradient-to-t from-violet-500 to-indigo-400"
                                        : "bg-muted/40"
                                    }`}
                                  />
                                  <span className="text-[9px] text-muted-foreground">
                                    {new Date(day.date + "T00:00:00").toLocaleDateString("en-US", {
                                      month: "short",
                                      day: "numeric",
                                    })}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>

                  {/* Recent Outcomes */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Recent Calls</CardTitle>
                      <CardDescription>Latest analyzed calls with outcomes</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {outcomes.length === 0 ? (
                        <p className="text-sm text-muted-foreground py-8 text-center">
                          No analyzed calls yet
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {outcomes.map((item, i) => (
                            <motion.div
                              key={item.id}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ delay: i * 0.03 }}
                              className="group flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-muted/50 cursor-pointer"
                              onClick={() => openCallLog(item.call_log_id)}
                            >
                              <div className="flex items-center gap-3">
                                {item.goal_outcome ? (
                                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                                ) : (
                                  <XCircle className="h-4 w-4 text-muted-foreground" />
                                )}
                                <div>
                                  <p className="text-sm font-medium capitalize">
                                    {(item.goal_outcome || "unknown").replace(/_/g, " ")}
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
                                        {Math.round(item.agent_word_share * 100)}% agent
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                {item.has_red_flags && (
                                  <Badge className={SEVERITY_COLORS[item.red_flag_max_severity || "medium"]}>
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

                {/* --- Alerts Tab --- */}
                <TabsContent value="alerts" className="space-y-4">
                  {!alerts || alerts.alerts.length === 0 ? (
                    <Card>
                      <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                        <BellOff className="mb-3 h-10 w-10 opacity-30" />
                        <p className="text-sm">No active alerts</p>
                        <p className="text-xs mt-1">
                          Red flag alerts will appear here when detected
                        </p>
                      </CardContent>
                    </Card>
                  ) : (
                    <>
                      <div className="flex items-center gap-2">
                        <Badge variant="destructive" className="gap-1">
                          <Bell className="h-3 w-3" />
                          {alerts.total_unacknowledged} unacknowledged
                        </Badge>
                      </div>
                      <div className="space-y-3">
                        {alerts.alerts.map((alert, i) => (
                          <motion.div
                            key={alert.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05 }}
                          >
                            <Card className="border-red-500/20">
                              <CardContent className="pt-4 space-y-3">
                                <div className="flex items-start justify-between">
                                  <div className="space-y-1">
                                    <div className="flex items-center gap-2">
                                      <AlertTriangle className="h-4 w-4 text-red-500" />
                                      <span className="text-sm font-medium">
                                        {alert.contact_name || "Unknown Contact"}
                                      </span>
                                      {alert.contact_phone && (
                                        <span className="text-xs text-muted-foreground">
                                          {alert.contact_phone}
                                        </span>
                                      )}
                                    </div>
                                    {alert.goal_outcome && (
                                      <p className="text-xs text-muted-foreground capitalize">
                                        Outcome: {alert.goal_outcome.replace(/_/g, " ")}
                                      </p>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {alert.red_flag_max_severity && (
                                      <Badge
                                        className={
                                          SEVERITY_COLORS[alert.red_flag_max_severity]
                                        }
                                      >
                                        {alert.red_flag_max_severity}
                                      </Badge>
                                    )}
                                    <span className="text-xs text-muted-foreground">
                                      {timeAgo(alert.created_at)}
                                    </span>
                                  </div>
                                </div>

                                {/* Red flag details */}
                                {alert.red_flags && alert.red_flags.length > 0 && (
                                  <div className="space-y-1.5 pl-6">
                                    {alert.red_flags.map((rf, j) => (
                                      <div
                                        key={`${rf.id}-${j}`}
                                        className="text-xs rounded bg-muted/50 p-2"
                                      >
                                        <div className="flex items-center gap-1.5 mb-0.5">
                                          <Badge
                                            variant="outline"
                                            className={`text-[10px] py-0 ${SEVERITY_COLORS[rf.severity]}`}
                                          >
                                            {rf.severity}
                                          </Badge>
                                          <span className="font-medium">{rf.id}</span>
                                        </div>
                                        {rf.evidence && (
                                          <p className="text-muted-foreground italic truncate">
                                            &ldquo;{rf.evidence}&rdquo;
                                          </p>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}

                                <div className="flex gap-2 pl-6">
                                  {alert.call_log_id && (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="h-7 text-xs"
                                      onClick={() => openCallLog(alert.call_log_id)}
                                    >
                                      <Eye className="h-3 w-3 mr-1" />
                                      View Call
                                    </Button>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-7 text-xs"
                                    onClick={() => handleAcknowledge(alert.id)}
                                  >
                                    <CheckCircle2 className="h-3 w-3 mr-1" />
                                    Acknowledge
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs"
                                    onClick={() => handleSnooze(alert.id)}
                                  >
                                    <Clock className="h-3 w-3 mr-1" />
                                    Snooze 24h
                                  </Button>
                                </div>
                              </CardContent>
                            </Card>
                          </motion.div>
                        ))}
                      </div>
                    </>
                  )}
                </TabsContent>

                {/* --- Red Flags Tab --- */}
                <TabsContent value="red-flags" className="space-y-4">
                  {redFlags.length === 0 ? (
                    <Card>
                      <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                        <Shield className="mb-3 h-10 w-10 opacity-30" />
                        <p className="text-sm">No red flags detected</p>
                      </CardContent>
                    </Card>
                  ) : (
                    <div className="space-y-4">
                      {redFlags.map((group, i) => {
                        const Icon = getSeverityIcon(group.severity);
                        return (
                          <motion.div
                            key={group.flag_id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05 }}
                          >
                            <Card>
                              <CardHeader className="pb-3">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <Icon className="h-4 w-4" />
                                    <CardTitle className="text-sm">
                                      {group.flag_id.replace(/_/g, " ")}
                                    </CardTitle>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <Badge
                                      className={SEVERITY_COLORS[group.severity]}
                                    >
                                      {group.severity}
                                    </Badge>
                                    <Badge variant="secondary">{group.count} occurrences</Badge>
                                  </div>
                                </div>
                              </CardHeader>
                              <CardContent>
                                <div className="space-y-2">
                                  {group.calls.slice(0, 5).map((call, j) => (
                                    <div
                                      key={call.analytics_id}
                                      className={`flex items-start justify-between text-xs rounded bg-muted/50 p-2 ${call.call_log_id ? "cursor-pointer hover:bg-muted transition-colors" : ""}`}
                                      onClick={() => call.call_log_id && openCallLog(call.call_log_id)}
                                    >
                                      <p className="text-muted-foreground italic flex-1 truncate mr-4">
                                        {call.evidence ? `"${call.evidence}"` : "No evidence recorded"}
                                      </p>
                                      <div className="flex items-center gap-2">
                                        <span className="text-muted-foreground whitespace-nowrap">
                                          {timeAgo(call.created_at)}
                                        </span>
                                        {call.call_log_id && (
                                          <ArrowRight className="h-3 w-3 text-muted-foreground" />
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                  {group.calls.length > 5 && (
                                    <p className="text-xs text-muted-foreground text-center">
                                      +{group.calls.length - 5} more
                                    </p>
                                  )}
                                </div>
                              </CardContent>
                            </Card>
                          </motion.div>
                        );
                      })}
                    </div>
                  )}
                </TabsContent>

                {/* --- Captured Data Tab --- */}
                <TabsContent value="captured-data" className="space-y-4">
                  {capturedData.length === 0 ? (
                    <Card>
                      <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                        <Database className="mb-3 h-10 w-10 opacity-30" />
                        <p className="text-sm">No captured data yet</p>
                        <p className="text-xs mt-1">
                          Data capture fields will populate as calls are analyzed
                        </p>
                      </CardContent>
                    </Card>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {capturedData.map((field, i) => (
                        <motion.div
                          key={field.field_id}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: i * 0.05 }}
                        >
                          <Card>
                            <CardHeader className="pb-3">
                              <div className="flex items-center justify-between">
                                <CardTitle className="text-sm capitalize">
                                  {field.field_id.replace(/_/g, " ")}
                                </CardTitle>
                                <Badge variant="secondary">
                                  {field.total_captured} captured
                                </Badge>
                              </div>
                            </CardHeader>
                            <CardContent>
                              <div className="space-y-1.5">
                                {field.values.slice(0, 8).map((v, j) => (
                                  <div
                                    key={`${v.value}-${j}`}
                                    className="flex items-center justify-between text-sm"
                                  >
                                    <span className="truncate flex-1 mr-2">
                                      {v.value}
                                    </span>
                                    {v.count != null && (
                                      <Badge variant="outline" className="text-xs">
                                        {v.count}
                                      </Badge>
                                    )}
                                  </div>
                                ))}
                                {field.values.length > 8 && (
                                  <p className="text-xs text-muted-foreground text-center">
                                    +{field.values.length - 8} more values
                                  </p>
                                )}
                              </div>
                            </CardContent>
                          </Card>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </>
          )}

          {!summary && !dataLoading && selectedBotId && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <BarChart3 className="mb-3 h-12 w-12 opacity-30" />
                <p className="text-sm font-medium">No Analytics Data</p>
                <p className="text-xs mt-1">
                  Analytics will appear here after calls are completed and analyzed
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </PageTransition>
    </>
  );
}
