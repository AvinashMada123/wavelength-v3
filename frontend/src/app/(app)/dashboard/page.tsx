"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Phone,
  Bot,
  Clock,
  CheckCircle2,
  Activity,
  PhoneCall,
  XCircle,
  ArrowRight,
} from "lucide-react";
import Link from "next/link";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBots, fetchCallLogs } from "@/lib/api";
import { formatDuration, formatPhoneNumber, timeAgo } from "@/lib/utils";
import type { BotConfig, CallLog } from "@/types/api";

const STATUS_ICONS: Record<string, typeof Clock> = {
  initiated: Clock,
  ringing: PhoneCall,
  "in-progress": Activity,
  completed: CheckCircle2,
  failed: XCircle,
  "no-answer": Phone,
};

const STAT_GRADIENTS = [
  "from-violet-500 to-indigo-500",
  "from-emerald-500 to-green-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
];

function getCallsByDay(calls: CallLog[]) {
  const days: { label: string; date: string; count: number }[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().slice(0, 10);
    const label = d.toLocaleDateString("en-US", { weekday: "short" });
    const count = calls.filter(
      (c) => c.created_at.slice(0, 10) === dateStr
    ).length;
    days.push({ label, date: dateStr, count });
  }
  return days;
}

export default function DashboardPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [b, c] = await Promise.all([fetchBots(), fetchCallLogs()]);
      setBots(b);
      setCalls(c);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const stats = useMemo(() => {
    const completed = calls.filter((c) => c.status === "completed");
    const totalDuration = completed.reduce(
      (sum, c) => sum + (c.call_duration || 0),
      0
    );
    const activeCalls = calls.filter((c) =>
      ["initiated", "ringing", "in-progress"].includes(c.status)
    ).length;

    return [
      {
        title: "Active Bots",
        value: bots.filter((b) => b.is_active).length,
        icon: Bot,
      },
      {
        title: "Total Calls",
        value: calls.length,
        icon: Phone,
      },
      {
        title: "Completed",
        value: completed.length,
        icon: CheckCircle2,
      },
      {
        title: "Total Duration",
        value: formatDuration(totalDuration),
        icon: Clock,
        isString: true,
      },
    ];
  }, [bots, calls]);

  const recentCalls = useMemo(
    () =>
      [...calls]
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        )
        .slice(0, 8),
    [calls]
  );

  const callsByDay = useMemo(() => getCallsByDay(calls), [calls]);
  const maxCount = Math.max(...callsByDay.map((d) => d.count), 1);

  return (
    <>
      <Header title="Dashboard" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((stat, i) => (
              <motion.div
                key={stat.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
              >
                <Card>
                  <CardContent className="flex items-center gap-4 pt-6">
                    <div
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${STAT_GRADIENTS[i]} text-white shadow-lg`}
                    >
                      <stat.icon className="h-5 w-5" />
                    </div>
                    <div>
                      {loading ? (
                        <Skeleton className="h-7 w-16" />
                      ) : (
                        <p className="text-2xl font-bold">
                          {stat.isString ? stat.value : stat.value}
                        </p>
                      )}
                      <p className="text-sm text-muted-foreground">
                        {stat.title}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Recent Calls */}
            <div className="lg:col-span-2">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle>Recent Calls</CardTitle>
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
                      {Array.from({ length: 4 }).map((_, i) => (
                        <Skeleton key={i} className="h-14 w-full" />
                      ))}
                    </div>
                  ) : recentCalls.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                      <Phone className="mb-3 h-10 w-10 opacity-30" />
                      <p className="text-sm">No calls yet</p>
                      <Button variant="link" size="sm" asChild>
                        <Link href="/calls">Make your first call</Link>
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {recentCalls.map((call, i) => {
                        const Icon =
                          STATUS_ICONS[call.status] || Clock;
                        return (
                          <motion.div
                            key={call.id}
                            initial={{ opacity: 0, x: -10 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: i * 0.04 }}
                            className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-muted/50"
                          >
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-sm font-medium">
                                {call.contact_name}
                              </p>
                              <div className="flex items-center gap-2 mt-0.5">
                                <p className="text-xs text-muted-foreground">
                                  {formatPhoneNumber(call.contact_phone)}
                                </p>
                                {call.call_duration ? (
                                  <span className="flex items-center gap-0.5 text-xs text-muted-foreground">
                                    <Clock className="h-3 w-3" />
                                    {formatDuration(call.call_duration)}
                                  </span>
                                ) : null}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <Badge
                                variant={
                                  call.status === "completed"
                                    ? "secondary"
                                    : call.status === "failed"
                                    ? "destructive"
                                    : "outline"
                                }
                                className="gap-1"
                              >
                                <Icon className="h-3 w-3" />
                                {call.status}
                              </Badge>
                              <span className="whitespace-nowrap text-xs text-muted-foreground">
                                {timeAgo(call.created_at)}
                              </span>
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Call Activity Chart */}
            <div>
              <Card className="h-full">
                <CardHeader>
                  <CardTitle>Call Activity</CardTitle>
                  <CardDescription>Last 7 days</CardDescription>
                </CardHeader>
                <CardContent>
                  {loading ? (
                    <div className="flex h-48 items-end justify-between gap-2">
                      {Array.from({ length: 7 }).map((_, i) => (
                        <Skeleton key={i} className="h-20 flex-1" />
                      ))}
                    </div>
                  ) : (
                    <div className="flex h-48 items-end justify-between gap-2">
                      {callsByDay.map((day, i) => {
                        const barHeight =
                          maxCount > 0
                            ? Math.max(
                                (day.count / maxCount) * 148,
                                day.count > 0 ? 8 : 4
                              )
                            : 4;
                        return (
                          <div
                            key={day.date}
                            className="group flex flex-1 flex-col items-center gap-1"
                          >
                            <span className="text-xs font-medium text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                              {day.count > 0 ? day.count : ""}
                            </span>
                            <motion.div
                              initial={{ height: 0 }}
                              animate={{ height: barHeight }}
                              transition={{
                                delay: i * 0.08,
                                duration: 0.6,
                                ease: [0.21, 0.47, 0.32, 0.98],
                              }}
                              className={`w-full max-w-[40px] rounded-t-sm ${
                                day.count > 0
                                  ? "bg-gradient-to-t from-violet-500 to-indigo-400"
                                  : "bg-muted/40"
                              }`}
                            />
                            <span className="text-[11px] text-muted-foreground">
                              {day.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Link href="/calls">
              <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
                <Card className="cursor-pointer transition-colors hover:border-violet-500/50">
                  <CardContent className="flex items-center gap-3 pt-6">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 text-white">
                      <PhoneCall className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium">New Call</p>
                      <p className="text-xs text-muted-foreground">
                        Trigger an outbound call
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </Link>
            <Link href="/bots">
              <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
                <Card className="cursor-pointer transition-colors hover:border-violet-500/50">
                  <CardContent className="flex items-center gap-3 pt-6">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-green-500 text-white">
                      <Bot className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium">Manage Bots</p>
                      <p className="text-xs text-muted-foreground">
                        Configure voice agents
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </Link>
            <Link href="/calls">
              <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
                <Card className="cursor-pointer transition-colors hover:border-violet-500/50">
                  <CardContent className="flex items-center gap-3 pt-6">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-amber-500 to-orange-500 text-white">
                      <Activity className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium">Call History</p>
                      <p className="text-xs text-muted-foreground">
                        View logs and summaries
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </Link>
          </div>
        </div>
      </PageTransition>
    </>
  );
}
