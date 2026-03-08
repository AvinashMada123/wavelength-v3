"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import {
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Pause,
  Play,
  Trash2,
  CheckCircle2,
  Clock,
  Loader2,
  AlertTriangle,
  XCircle,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  ListOrdered,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchQueuedCalls,
  fetchQueueStats,
  fetchCircuitBreakers,
  cancelQueuedCall,
  bulkCancelQueuedCalls,
  bulkApproveHeldCalls,
  openCircuitBreaker,
  resetCircuitBreaker,
  fetchBots,
} from "@/lib/api";
import { formatPhoneNumber, timeAgo, cn } from "@/lib/utils";
import type { QueuedCall, CircuitBreakerState, QueueStats, BotConfig } from "@/types/api";

const QUEUE_STATUS_CONFIG: Record<
  string,
  { color: string; bgColor: string; icon: typeof Clock }
> = {
  queued: { color: "text-blue-400", bgColor: "bg-blue-500/10 border-blue-500/20", icon: Clock },
  processing: { color: "text-amber-400", bgColor: "bg-amber-500/10 border-amber-500/20", icon: Loader2 },
  completed: { color: "text-emerald-400", bgColor: "bg-emerald-500/10 border-emerald-500/20", icon: CheckCircle2 },
  failed: { color: "text-red-400", bgColor: "bg-red-500/10 border-red-500/20", icon: XCircle },
  held: { color: "text-orange-400", bgColor: "bg-orange-500/10 border-orange-500/20", icon: Pause },
  cancelled: { color: "text-zinc-400", bgColor: "bg-zinc-500/10 border-zinc-500/20", icon: XCircle },
};

function QueueStatusBadge({ status }: { status: string }) {
  const config = QUEUE_STATUS_CONFIG[status] || QUEUE_STATUS_CONFIG.queued;
  const Icon = config.icon;
  return (
    <Badge variant="outline" className={cn("gap-1", config.bgColor)}>
      <Icon className={cn("h-3 w-3", config.color, status === "processing" && "animate-spin")} />
      {status}
    </Badge>
  );
}

function CircuitBreakerCard({
  cb,
  onPause,
  onResume,
  loading,
}: {
  cb: CircuitBreakerState;
  onPause: () => void;
  onResume: () => void;
  loading: boolean;
}) {
  const isOpen = cb.state === "open";
  return (
    <Card className={cn(
      "transition-all",
      isOpen && "border-red-500/40 bg-red-500/5"
    )}>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
              isOpen
                ? "bg-red-500/10 text-red-400"
                : "bg-emerald-500/10 text-emerald-400"
            )}>
              {isOpen ? <ShieldOff className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
            </div>
            <div>
              <p className="font-semibold">{cb.bot_name || "Unknown Bot"}</p>
              <p className="text-xs text-muted-foreground">
                {isOpen ? (
                  <span className="text-red-400">
                    PAUSED {cb.opened_by === "auto" ? "(auto-tripped)" : "(manual)"}
                  </span>
                ) : (
                  <span className="text-emerald-400">Active</span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-right mr-3">
              <p className="text-xs text-muted-foreground">Failures</p>
              <p className={cn(
                "text-lg font-bold",
                cb.consecutive_failures > 0 ? "text-red-400" : "text-muted-foreground"
              )}>
                {cb.consecutive_failures}/{cb.failure_threshold}
              </p>
            </div>
            {isOpen ? (
              <Button
                size="sm"
                onClick={onResume}
                disabled={loading}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Play className="mr-1 h-3 w-3" />}
                Resume
              </Button>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                onClick={onPause}
                disabled={loading}
              >
                {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Pause className="mr-1 h-3 w-3" />}
                Pause
              </Button>
            )}
          </div>
        </div>
        {isOpen && cb.last_failure_reason && (
          <div className="mt-3 rounded-md bg-red-500/10 border border-red-500/20 p-2.5 text-xs text-red-300">
            <AlertTriangle className="inline h-3 w-3 mr-1" />
            <span className="font-medium">Last error:</span> {cb.last_failure_reason}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const PAGE_SIZE = 25;

export default function QueuePage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [queuedCalls, setQueuedCalls] = useState<QueuedCall[]>([]);
  const [circuitBreakers, setCircuitBreakers] = useState<CircuitBreakerState[]>([]);
  const [queueStats, setQueueStats] = useState<QueueStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filters
  const [filterBotId, setFilterBotId] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("actionable");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(0);

  // Selection for bulk actions
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Confirm dialog
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    title: string;
    description: string;
    action: () => Promise<void>;
  } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [calls, cbs, stats] = await Promise.all([
        fetchQueuedCalls({
          bot_id: filterBotId !== "all" ? filterBotId : undefined,
          limit: 500,
        }),
        fetchCircuitBreakers(),
        fetchQueueStats(),
      ]);
      setQueuedCalls(calls);
      setCircuitBreakers(cbs);
      setQueueStats(stats);
    } catch {
      // silent polling
    } finally {
      setLoading(false);
    }
  }, [filterBotId]);

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    loadData();
  }, [loadData]);

  // Poll every 5s
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(loadData, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadData]);

  // Filter calls
  const filteredCalls = useMemo(() => {
    let result = queuedCalls;
    if (filterStatus === "actionable") {
      result = result.filter((c) => ["queued", "held", "processing"].includes(c.status));
    } else if (filterStatus !== "all") {
      result = result.filter((c) => c.status === filterStatus);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (c) =>
          c.contact_name.toLowerCase().includes(q) ||
          c.contact_phone.includes(q) ||
          (c.bot_name && c.bot_name.toLowerCase().includes(q))
      );
    }
    return result;
  }, [queuedCalls, filterStatus, searchQuery]);

  const totalPages = Math.ceil(filteredCalls.length / PAGE_SIZE);
  const paginatedCalls = filteredCalls.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => {
    setPage(0);
  }, [filterBotId, filterStatus, searchQuery]);

  // Summary stats
  const totalQueued = queueStats.reduce((sum, s) => sum + s.queued, 0);
  const totalHeld = queueStats.reduce((sum, s) => sum + s.held, 0);
  const totalProcessing = queueStats.reduce((sum, s) => sum + s.processing, 0);
  const openBreakers = circuitBreakers.filter((cb) => cb.state === "open").length;

  // Actions
  async function handlePauseBot(botId: string) {
    setActionLoading(botId);
    try {
      await openCircuitBreaker(botId);
      toast.success("Bot paused — incoming calls will be held");
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to pause");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleResumeBot(botId: string) {
    setActionLoading(botId);
    try {
      await resetCircuitBreaker(botId);
      toast.success("Bot resumed — held calls released to queue");
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to resume");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleApproveAll(botId: string) {
    setActionLoading(`approve-${botId}`);
    try {
      await bulkApproveHeldCalls(botId);
      toast.success("All held calls approved and released");
      await loadData();
      setSelectedIds(new Set());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleCancelSelected() {
    if (selectedIds.size === 0) return;
    setActionLoading("bulk-cancel");
    try {
      const res = await bulkCancelQueuedCalls(Array.from(selectedIds));
      toast.success(`Cancelled ${res.cancelled} call(s)`);
      setSelectedIds(new Set());
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleCancelSingle(queueId: string) {
    try {
      await cancelQueuedCall(queueId);
      toast.success("Call cancelled");
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel");
    }
  }

  function toggleSelection(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    const cancelable = paginatedCalls.filter((c) => ["queued", "held"].includes(c.status));
    if (selectedIds.size === cancelable.length && cancelable.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(cancelable.map((c) => c.id)));
    }
  }

  // Bots with held calls (for approve buttons)
  const botsWithHeld = useMemo(() => {
    const map = new Map<string, { botName: string; count: number }>();
    queuedCalls
      .filter((c) => c.status === "held")
      .forEach((c) => {
        const existing = map.get(c.bot_id);
        if (existing) existing.count++;
        else map.set(c.bot_id, { botName: c.bot_name || "Unknown", count: 1 });
      });
    return map;
  }, [queuedCalls]);

  return (
    <>
      <Header title="Call Queue" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { icon: Clock, label: "Queued", value: totalQueued, gradient: "from-blue-500 to-cyan-500" },
              { icon: Pause, label: "Held", value: totalHeld, gradient: "from-orange-500 to-amber-500" },
              { icon: Loader2, label: "Processing", value: totalProcessing, gradient: "from-violet-500 to-indigo-500" },
              { icon: ShieldAlert, label: "Breakers Open", value: openBreakers, gradient: openBreakers > 0 ? "from-red-500 to-rose-500" : "from-emerald-500 to-green-500" },
            ].map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06 }}
              >
                <Card>
                  <CardContent className="flex items-center gap-3 pt-6">
                    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${stat.gradient} text-white`}>
                      <stat.icon className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-xl font-bold">{stat.value}</p>
                      <p className="text-xs text-muted-foreground">{stat.label}</p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>

          {/* Circuit Breaker Status */}
          {circuitBreakers.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Circuit Breakers
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {circuitBreakers.map((cb) => (
                  <CircuitBreakerCard
                    key={cb.bot_id}
                    cb={cb}
                    onPause={() => handlePauseBot(cb.bot_id)}
                    onResume={() => handleResumeBot(cb.bot_id)}
                    loading={actionLoading === cb.bot_id}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Held calls approval banner */}
          {botsWithHeld.size > 0 && (
            <Card className="border-orange-500/40 bg-orange-500/5">
              <CardContent className="pt-6">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-orange-400 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="font-semibold text-orange-200">Calls on hold</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      The circuit breaker has paused calls for the following bots. Review the errors and approve to resume.
                    </p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      {Array.from(botsWithHeld.entries()).map(([botId, { botName, count }]) => (
                        <Button
                          key={botId}
                          size="sm"
                          variant="outline"
                          className="border-orange-500/30 hover:bg-orange-500/10"
                          onClick={() => {
                            setConfirmDialog({
                              open: true,
                              title: `Approve ${count} held call(s) for ${botName}?`,
                              description:
                                "This will reset the circuit breaker and release all held calls back into the queue for processing.",
                              action: async () => {
                                await handleApproveAll(botId);
                                setConfirmDialog(null);
                              },
                            });
                          }}
                          disabled={actionLoading === `approve-${botId}`}
                        >
                          {actionLoading === `approve-${botId}` ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : (
                            <Play className="mr-1 h-3 w-3" />
                          )}
                          {botName} ({count} held)
                        </Button>
                      ))}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Queue table */}
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <CardTitle className="text-base flex items-center gap-2">
                    <ListOrdered className="h-4 w-4" />
                    Call Queue
                  </CardTitle>
                  <CardDescription>
                    {filteredCalls.length} call{filteredCalls.length !== 1 ? "s" : ""}
                    {selectedIds.size > 0 && (
                      <span className="text-foreground ml-2">
                        ({selectedIds.size} selected)
                      </span>
                    )}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {/* Bulk cancel */}
                  {selectedIds.size > 0 && (
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={handleCancelSelected}
                      disabled={actionLoading === "bulk-cancel"}
                    >
                      {actionLoading === "bulk-cancel" ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <Trash2 className="mr-1 h-3 w-3" />
                      )}
                      Cancel Selected
                    </Button>
                  )}
                  {/* Search */}
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search..."
                      className="pl-8 w-48"
                    />
                    {searchQuery && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="absolute right-0.5 top-1/2 -translate-y-1/2 h-7 w-7"
                        onClick={() => setSearchQuery("")}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                  {/* Bot filter */}
                  <Select value={filterBotId} onValueChange={setFilterBotId}>
                    <SelectTrigger className="w-40">
                      <SelectValue placeholder="All bots" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All bots</SelectItem>
                      {bots.map((bot) => (
                        <SelectItem key={bot.id} value={bot.id}>
                          {bot.agent_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {/* Status filter */}
                  <Select value={filterStatus} onValueChange={setFilterStatus}>
                    <SelectTrigger className="w-40">
                      <SelectValue placeholder="Status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="actionable">Actionable</SelectItem>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="queued">Queued</SelectItem>
                      <SelectItem value="held">Held</SelectItem>
                      <SelectItem value="processing">Processing</SelectItem>
                      <SelectItem value="completed">Completed</SelectItem>
                      <SelectItem value="failed">Failed</SelectItem>
                      <SelectItem value="cancelled">Cancelled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : filteredCalls.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <ListOrdered className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm">No calls in queue</p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10">
                          <input
                            type="checkbox"
                            checked={
                              paginatedCalls.filter((c) => ["queued", "held"].includes(c.status)).length > 0 &&
                              paginatedCalls
                                .filter((c) => ["queued", "held"].includes(c.status))
                                .every((c) => selectedIds.has(c.id))
                            }
                            onChange={toggleSelectAll}
                            className="rounded border-zinc-600"
                          />
                        </TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Contact</TableHead>
                        <TableHead>Phone</TableHead>
                        <TableHead>Bot</TableHead>
                        <TableHead>Source</TableHead>
                        <TableHead>Error</TableHead>
                        <TableHead>Queued</TableHead>
                        <TableHead className="w-10"></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {paginatedCalls.map((call) => {
                        const cancelable = ["queued", "held"].includes(call.status);
                        return (
                          <TableRow key={call.id}>
                            <TableCell>
                              {cancelable && (
                                <input
                                  type="checkbox"
                                  checked={selectedIds.has(call.id)}
                                  onChange={() => toggleSelection(call.id)}
                                  className="rounded border-zinc-600"
                                />
                              )}
                            </TableCell>
                            <TableCell>
                              <QueueStatusBadge status={call.status} />
                            </TableCell>
                            <TableCell className="font-medium">
                              {call.contact_name}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {formatPhoneNumber(call.contact_phone)}
                            </TableCell>
                            <TableCell className="text-sm">
                              {call.bot_name || "-"}
                            </TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-[10px]">
                                {call.source}
                              </Badge>
                            </TableCell>
                            <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                              {call.error_message || "-"}
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                              {timeAgo(call.created_at)}
                            </TableCell>
                            <TableCell>
                              {cancelable && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                  onClick={() => handleCancelSingle(call.id)}
                                >
                                  <X className="h-3.5 w-3.5" />
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>

                  {/* Pagination */}
                  {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-4 pt-4 border-t">
                      <p className="text-sm text-muted-foreground">
                        Page {page + 1} of {totalPages}
                      </p>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={page === 0}
                          onClick={() => setPage((p) => p - 1)}
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={page >= totalPages - 1}
                          onClick={() => setPage((p) => p + 1)}
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>

      {/* Confirm Dialog */}
      <Dialog
        open={confirmDialog?.open || false}
        onOpenChange={(open) => !open && setConfirmDialog(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{confirmDialog?.title}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {confirmDialog?.description}
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setConfirmDialog(null)}>
              Cancel
            </Button>
            <Button onClick={confirmDialog?.action}>
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
