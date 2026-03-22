"use client";

import { Suspense, useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Phone,
  PhoneCall,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Search,
  Download,
  X,

  ChevronLeft,
  ChevronRight,
  RefreshCw,
  FileText,
  PhoneOff,
  AlertTriangle,
  Shield,
  Target,
  Database,
  ExternalLink,
  MessageSquareText,
  ChevronDown,
  ChevronUp,
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
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fetchBots, fetchCallLogs, fetchCallDetail, getRecordingUrl, exportCallLogs } from "@/lib/api";
import { exportCallsCSV } from "@/lib/call-logs-export";
import { formatDate, formatDuration, formatPhoneNumber, timeAgo, cn } from "@/lib/utils";
import { TimeDisplay } from "@/components/time-display";
import { CALL_STATUS_CONFIG, INTEREST_CONFIG, SEVERITY_COLORS } from "@/lib/status-config";
import { DateRangePicker, type DateRange } from "@/components/date-range-picker";
import type { BotConfig, CallLog, CallAnalyticsData } from "@/types/api";

// ---------- Status badge ----------

function StatusBadge({ status }: { status: string }) {
  const config = CALL_STATUS_CONFIG[status] || {
    variant: "outline" as const,
    icon: Clock,
    color: "text-muted-foreground",
  };
  const Icon = config.icon;
  const isActive = ["initiated", "ringing", "in-progress"].includes(status);
  return (
    <Badge variant={config.variant} className="gap-1">
      <span className="relative">
        <Icon className={`h-3 w-3 ${config.color}`} />
        {isActive && (
          <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-green-400 animate-ping" />
        )}
      </span>
      {status}
    </Badge>
  );
}

function InterestBadge({ level }: { level: string }) {
  const config = INTEREST_CONFIG[level];
  if (!config) return <span className="text-muted-foreground">-</span>;
  return (
    <Badge variant="outline" className={cn("text-[10px]", config.color)}>
      {config.label}
    </Badge>
  );
}

// ---------- Score badge ----------

function ScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-muted-foreground">-</span>;
  const color =
    score >= 80
      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
      : score >= 50
        ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
        : "bg-red-500/10 text-red-400 border-red-500/20";
  return (
    <Badge variant="outline" className={cn("text-[10px] font-semibold tabular-nums", color)}>
      {score}
    </Badge>
  );
}

// ---------- Sentiment badge ----------

const SENTIMENT_CONFIG: Record<string, { emoji: string; color: string }> = {
  positive: { emoji: "+", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  neutral: { emoji: "~", color: "bg-slate-500/10 text-slate-400 border-slate-500/20" },
  negative: { emoji: "-", color: "bg-red-500/10 text-red-400 border-red-500/20" },
  mixed: { emoji: "+/-", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
};

function SentimentBadge({ sentiment }: { sentiment: string | null | undefined }) {
  if (!sentiment) return <span className="text-muted-foreground">-</span>;
  const config = SENTIMENT_CONFIG[sentiment.toLowerCase()] || SENTIMENT_CONFIG.neutral;
  return (
    <Badge variant="outline" className={cn("text-[10px]", config.color)}>
      {config.emoji} {sentiment}
    </Badge>
  );
}

// ---------- Page ----------

const PAGE_SIZE = 25;

export default function CallLogsPage() {
  return (
    <Suspense>
      <CallLogsPageInner />
    </Suspense>
  );
}

function CallLogsPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [bots, setBots] = useState<BotConfig[]>([]);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [totalCalls, setTotalCalls] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Filters — initialize from URL params for deep linking
  const [filterBotId, setFilterBotId] = useState(searchParams.get("bot_id") || "all");
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterGoalOutcome, setFilterGoalOutcome] = useState(searchParams.get("goal_outcome") || "all");
  const [searchQuery, setSearchQuery] = useState("");
  const [dateRange, setDateRange] = useState<DateRange>({ from: null, to: null });
  const [page, setPage] = useState(0);

  // Selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);

  // Transcript search
  const [transcriptSearch, setTranscriptSearch] = useState("");
  // Expanded summary rows
  const [expandedSummaries, setExpandedSummaries] = useState<Set<string>>(new Set());

  // Detail modal
  const [selectedCall, setSelectedCall] = useState<CallLog | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Deep-link: auto-open call from ?call_id= param
  const deepLinkCallId = searchParams.get("call_id");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------- Data loading ----------

  const loadCalls = useCallback(async () => {
    try {
      const data = await fetchCallLogs({
        botId: filterBotId !== "all" ? filterBotId : undefined,
        goalOutcome: filterGoalOutcome !== "all" ? filterGoalOutcome : undefined,
        status: filterStatus !== "all" ? filterStatus : undefined,
        dateFrom: dateRange.from ? new Date(dateRange.from).toISOString() : undefined,
        dateTo: dateRange.to ? new Date(dateRange.to).toISOString() : undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setCalls(data.items);
      setTotalCalls(data.total);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [filterBotId, filterGoalOutcome, filterStatus, dateRange, page]);

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    loadCalls();
  }, [loadCalls]);

  // Smart polling
  useEffect(() => {
    const hasActive = calls.some((c) =>
      ["initiated", "ringing", "in-progress"].includes(c.status)
    );
    const interval = hasActive ? 3000 : 30000;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(loadCalls, interval);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [calls, loadCalls]);

  // Deep-link: auto-open a specific call from URL param
  useEffect(() => {
    if (deepLinkCallId && !loading) {
      openCallDetail({ id: deepLinkCallId } as CallLog);
      // Clear the param so closing the modal doesn't re-open
      router.replace("/call-logs", { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkCallId, loading]);

  async function handleRefresh() {
    setRefreshing(true);
    await loadCalls();
    setRefreshing(false);
    toast.success("Refreshed");
  }

  function navigateToDetail(call: CallLog) {
    router.push(`/calls/${call.id}`);
  }

  async function openCallDetail(call: CallLog) {
    setSelectedCall(call);
    setLoadingDetail(true);
    try {
      const full = await fetchCallDetail(call.id);
      setSelectedCall(full);
    } catch {
      // keep the light version
    } finally {
      setLoadingDetail(false);
    }
  }

  // ---------- Bot name lookup ----------

  const botNameMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of bots) m.set(b.id, b.agent_name);
    return m;
  }, [bots]);

  // ---------- Goal outcome options (derived from loaded calls) ----------

  const goalOutcomeOptions = useMemo(() => {
    const outcomes = new Set<string>();
    for (const c of calls) {
      if (c.outcome) outcomes.add(c.outcome);
    }
    return Array.from(outcomes).sort();
  }, [calls]);

  // ---------- Filtering ----------

  const filteredCalls = useMemo(() => {
    let result = calls;

    // Status and date filters are now server-side

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (c) =>
          c.contact_name.toLowerCase().includes(q) ||
          c.contact_phone.includes(q) ||
          (c.summary && c.summary.toLowerCase().includes(q))
      );
    }

    // Transcript content search
    if (transcriptSearch.trim()) {
      const tq = transcriptSearch.toLowerCase();
      result = result.filter((c) =>
        c.metadata?.transcript?.some((t) =>
          t.content.toLowerCase().includes(tq)
        )
      );
    }

    return result;
  }, [calls, filterStatus, searchQuery, dateRange, transcriptSearch]);

  const totalPages = Math.ceil(totalCalls / PAGE_SIZE);
  const paginatedCalls = filteredCalls;

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
    setSelectedIds(new Set());
    setSelectAllMatching(false);
  }, [filterBotId, filterStatus, filterGoalOutcome, searchQuery, dateRange, transcriptSearch]);

  // ---------- Selection ----------

  const allOnPageSelected =
    paginatedCalls.length > 0 &&
    paginatedCalls.every((c) => selectedIds.has(c.id));
  const someOnPageSelected =
    paginatedCalls.some((c) => selectedIds.has(c.id)) && !allOnPageSelected;

  function toggleSelectAll() {
    setSelectAllMatching(false);
    if (allOnPageSelected) {
      const next = new Set(selectedIds);
      for (const c of paginatedCalls) next.delete(c.id);
      setSelectedIds(next);
    } else {
      const next = new Set(selectedIds);
      for (const c of paginatedCalls) next.add(c.id);
      setSelectedIds(next);
    }
  }

  function toggleSelect(id: string) {
    setSelectAllMatching(false);
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  }

  // ---------- Export ----------

  async function handleExport() {
    try {
      toast.info("Fetching full call data for export...");
      const fullCalls = await exportCallLogs({
        botId: filterBotId !== "all" ? filterBotId : undefined,
        goalOutcome: filterGoalOutcome !== "all" ? filterGoalOutcome : undefined,
        status: filterStatus !== "all" ? filterStatus : undefined,
        dateFrom: dateRange.from ? new Date(dateRange.from).toISOString() : undefined,
        dateTo: dateRange.to ? new Date(dateRange.to).toISOString() : undefined,
      });
      let toExport = fullCalls;
      // Client-side search filter (not available server-side)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        toExport = toExport.filter(
          (c) =>
            c.contact_name.toLowerCase().includes(q) ||
            c.contact_phone.includes(q) ||
            (c.summary && c.summary.toLowerCase().includes(q))
        );
      }
      // Filter by selection only if not "select all matching"
      if (selectedIds.size > 0 && !selectAllMatching) {
        toExport = toExport.filter((c) => selectedIds.has(c.id));
      }
      exportCallsCSV(toExport);
      toast.success(`Exported ${toExport.length} calls`);
    } catch {
      toast.error("Export failed");
    }
  }

  // ---------- Filter state ----------

  const hasFilters =
    searchQuery ||
    transcriptSearch ||
    filterStatus !== "all" ||
    filterBotId !== "all" ||
    filterGoalOutcome !== "all" ||
    dateRange.from ||
    dateRange.to;

  function clearFilters() {
    setSearchQuery("");
    setTranscriptSearch("");
    setFilterStatus("all");
    setFilterBotId("all");
    setFilterGoalOutcome("all");
    setDateRange({ from: null, to: null });
  }

  function toggleSummaryExpand(id: string) {
    setExpandedSummaries((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Helper to extract score/sentiment from analytics captured_data
  function getCallScore(call: CallLog): number | null {
    const cd = call.analytics?.captured_data;
    if (!cd) return null;
    if (typeof cd.score === "number") return cd.score;
    if (typeof cd.call_score === "number") return cd.call_score;
    return null;
  }

  function getCallSentiment(call: CallLog): string | null {
    const cd = call.analytics?.captured_data;
    if (!cd) return null;
    if (typeof cd.sentiment === "string") return cd.sentiment;
    if (typeof cd.overall_sentiment === "string") return cd.overall_sentiment;
    return null;
  }

  // ---------- Pagination helpers ----------

  function getPageNumbers(): (number | "ellipsis")[] {
    const p = page + 1; // 1-based for display
    const pages: (number | "ellipsis")[] = [];
    if (totalPages <= 5) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (p > 3) pages.push("ellipsis");
      const rangeStart = Math.max(2, p - 1);
      const rangeEnd = Math.min(totalPages - 1, p + 1);
      for (let i = rangeStart; i <= rangeEnd; i++) pages.push(i);
      if (p < totalPages - 2) pages.push("ellipsis");
      pages.push(totalPages);
    }
    return pages;
  }

  return (
    <>
      <Header title="Call Logs" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Header row */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">Call Logs</h2>
              <p className="text-sm text-muted-foreground">
                View, filter, and export your complete call history
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5 mr-1.5", refreshing && "animate-spin")}
              />
              {refreshing ? "Refreshing..." : "Refresh"}
            </Button>
          </div>

          <Card>
            <CardHeader className="pb-4">
              {/* Toolbar */}
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  {/* Search */}
                  <div className="relative flex-1 min-w-[200px]">
                    <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search by name, phone, or summary..."
                      className="pl-8 h-9"
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

                  {/* Status filter */}
                  <Select value={filterStatus} onValueChange={setFilterStatus}>
                    <SelectTrigger className="w-36 h-9">
                      <SelectValue placeholder="All statuses" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All statuses</SelectItem>
                      {Object.keys(CALL_STATUS_CONFIG).map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Bot filter */}
                  <Select value={filterBotId} onValueChange={setFilterBotId}>
                    <SelectTrigger className="w-40 h-9">
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

                  {/* Goal outcome filter */}
                  <Select value={filterGoalOutcome} onValueChange={setFilterGoalOutcome}>
                    <SelectTrigger className="w-40 h-9">
                      <SelectValue placeholder="All outcomes" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All outcomes</SelectItem>
                      {goalOutcomeOptions.map((o) => (
                        <SelectItem key={o} value={o}>
                          {o.replace(/_/g, " ")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Date range */}
                  <DateRangePicker
                    value={dateRange}
                    onChange={setDateRange}
                    className="h-9"
                  />

                  {/* Transcript search */}
                  <div className="relative min-w-[180px]">
                    <MessageSquareText className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={transcriptSearch}
                      onChange={(e) => setTranscriptSearch(e.target.value)}
                      placeholder="Search transcripts..."
                      className="pl-8 h-9 text-xs"
                    />
                    {transcriptSearch && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="absolute right-0.5 top-1/2 -translate-y-1/2 h-7 w-7"
                        onClick={() => setTranscriptSearch("")}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </div>

                  {/* Clear filters */}
                  {hasFilters && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={clearFilters}
                      className="text-xs gap-1"
                    >
                      <X className="h-3 w-3" />
                      Clear
                    </Button>
                  )}

                  {/* Export */}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleExport}
                    className="gap-1.5 ml-auto"
                  >
                    <Download className="h-3.5 w-3.5" />
                    {selectAllMatching
                      ? `Export all ${totalCalls}`
                      : selectedIds.size > 0
                        ? `Export ${selectedIds.size} selected`
                        : "Export CSV"}
                  </Button>
                </div>

                {/* Selection + count indicator */}
                {(selectedIds.size > 0 ||
                  selectAllMatching ||
                  (hasFilters && filteredCalls.length !== calls.length)) && (
                  <div className="flex items-center gap-3">
                    {(selectedIds.size > 0 || selectAllMatching) && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-violet-400 font-medium">
                          {selectAllMatching
                            ? `All ${totalCalls} selected`
                            : `${selectedIds.size} selected`}
                        </span>
                        {!selectAllMatching && totalCalls > filteredCalls.length && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 text-xs px-2"
                            onClick={() => {
                              setSelectAllMatching(true);
                              setSelectedIds(
                                new Set(filteredCalls.map((c) => c.id))
                              );
                            }}
                          >
                            Select all {totalCalls}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-xs px-2"
                          onClick={() => {
                            setSelectedIds(new Set());
                            setSelectAllMatching(false);
                          }}
                        >
                          Clear
                        </Button>
                      </div>
                    )}
                    {hasFilters &&
                      filteredCalls.length !== calls.length &&
                      selectedIds.size === 0 &&
                      !selectAllMatching && (
                        <p className="text-xs text-muted-foreground">
                          Showing {filteredCalls.length} of {calls.length} calls
                        </p>
                      )}
                  </div>
                )}
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : filteredCalls.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <PhoneOff className="mb-3 h-12 w-12 opacity-30" />
                  <p className="font-medium">
                    {calls.length === 0 ? "No calls yet" : "No matching calls"}
                  </p>
                  <p className="text-sm mt-1">
                    {calls.length === 0
                      ? "Initiate your first call to see logs here."
                      : "Try adjusting your filters."}
                  </p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10">
                          <input
                            type="checkbox"
                            checked={allOnPageSelected}
                            ref={(el) => {
                              if (el) el.indeterminate = someOnPageSelected;
                            }}
                            onChange={toggleSelectAll}
                            className="h-4 w-4 rounded border-muted-foreground/40 accent-violet-500 cursor-pointer"
                          />
                        </TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Contact</TableHead>
                        <TableHead>Phone</TableHead>
                        <TableHead>Bot</TableHead>
                        <TableHead>Duration</TableHead>
                        <TableHead>Score</TableHead>
                        <TableHead>Sentiment</TableHead>
                        <TableHead>Outcome</TableHead>
                        <TableHead>Interest</TableHead>
                        <TableHead>Summary</TableHead>
                        <TableHead>Time</TableHead>
                        <TableHead className="w-10" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {paginatedCalls.map((call, index) => (
                        <motion.tr
                          key={call.id}
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.15, delay: index * 0.02 }}
                          className={cn(
                            "hover:bg-muted/50 border-b transition-colors cursor-pointer",
                            selectedIds.has(call.id) && "bg-violet-500/5"
                          )}
                          onClick={() => navigateToDetail(call)}
                        >
                          <TableCell onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={selectedIds.has(call.id)}
                              onChange={() => toggleSelect(call.id)}
                              className="h-4 w-4 rounded border-muted-foreground/40 accent-violet-500 cursor-pointer"
                            />
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={call.status} />
                          </TableCell>
                          <TableCell>
                            <p className="font-medium">{call.contact_name}</p>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {formatPhoneNumber(call.contact_phone)}
                          </TableCell>
                          <TableCell>
                            {botNameMap.get(call.bot_id) ? (
                              <Badge
                                variant="outline"
                                className="text-[10px] font-normal"
                              >
                                {botNameMap.get(call.bot_id)}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground text-xs">
                                -
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {call.call_duration
                              ? formatDuration(call.call_duration)
                              : "-"}
                          </TableCell>
                          <TableCell>
                            <ScoreBadge score={getCallScore(call)} />
                          </TableCell>
                          <TableCell>
                            <SentimentBadge sentiment={getCallSentiment(call)} />
                          </TableCell>
                          <TableCell>
                            {call.outcome ? (
                              <Badge variant="outline" className="text-xs">
                                {call.outcome}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {call.metadata?.interest_level ? (
                              <InterestBadge level={call.metadata.interest_level} />
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell className="max-w-[200px]" onClick={(e) => e.stopPropagation()}>
                            {call.summary ? (
                              <div>
                                <p className={cn(
                                  "text-xs text-muted-foreground",
                                  !expandedSummaries.has(call.id) && "line-clamp-2"
                                )}>
                                  {call.summary}
                                </p>
                                {call.summary.length > 80 && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-5 px-1 text-[10px] text-violet-400 hover:text-violet-300 mt-0.5"
                                    onClick={() => toggleSummaryExpand(call.id)}
                                  >
                                    {expandedSummaries.has(call.id) ? (
                                      <>Less <ChevronUp className="h-3 w-3 ml-0.5" /></>
                                    ) : (
                                      <>More <ChevronDown className="h-3 w-3 ml-0.5" /></>
                                    )}
                                  </Button>
                                )}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell className="text-muted-foreground whitespace-nowrap text-sm">
                            <TimeDisplay date={call.created_at} />
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={(e) => {
                                e.stopPropagation();
                                navigateToDetail(call);
                              }}
                              title="View full details"
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </Button>
                          </TableCell>
                        </motion.tr>
                      ))}
                    </TableBody>
                  </Table>

                  {/* Pagination */}
                  {totalPages > 0 && (
                    <div className="flex items-center justify-between pt-2">
                      <p className="text-sm text-muted-foreground">
                        Showing {page * PAGE_SIZE + 1}-
                        {Math.min((page + 1) * PAGE_SIZE, totalCalls)}{" "}
                        of {totalCalls} calls
                      </p>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8"
                          disabled={page === 0}
                          onClick={() => setPage((p) => p - 1)}
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </Button>
                        {getPageNumbers().map((pn, idx) =>
                          pn === "ellipsis" ? (
                            <span
                              key={`e-${idx}`}
                              className="px-2 text-sm text-muted-foreground"
                            >
                              ...
                            </span>
                          ) : (
                            <Button
                              key={pn}
                              variant={pn === page + 1 ? "default" : "outline"}
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => setPage(pn - 1)}
                            >
                              {pn}
                            </Button>
                          )
                        )}
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8"
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

      {/* Call Detail Modal */}
      <Dialog
        open={!!selectedCall}
        onOpenChange={(open) => !open && setSelectedCall(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Call Details</DialogTitle>
          </DialogHeader>
          {selectedCall && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold text-lg">
                    {selectedCall.contact_name}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {formatPhoneNumber(selectedCall.contact_phone)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {selectedCall.metadata?.interest_level && (
                    <InterestBadge level={selectedCall.metadata.interest_level} />
                  )}
                  <StatusBadge status={selectedCall.status} />
                </div>
              </div>

              <Separator />

              <Tabs defaultValue="details">
                <TabsList className="w-full">
                  <TabsTrigger value="details" className="flex-1">Details</TabsTrigger>
                  <TabsTrigger
                    value="transcript"
                    className="flex-1"
                    disabled={!selectedCall.metadata?.transcript?.length}
                  >
                    Transcript
                    {selectedCall.metadata?.transcript?.length ? (
                      <span className="ml-1.5 text-[10px] text-muted-foreground">
                        ({selectedCall.metadata.transcript.length})
                      </span>
                    ) : null}
                  </TabsTrigger>
                  <TabsTrigger
                    value="recording"
                    className="flex-1"
                    disabled={!selectedCall.metadata?.recording_url}
                  >
                    Recording
                  </TabsTrigger>
                </TabsList>

                {/* Details Tab */}
                <TabsContent value="details" className="mt-4">
                  <ScrollArea className="h-[400px]">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-muted-foreground">Bot</p>
                      <p className="font-medium">
                        {botNameMap.get(selectedCall.bot_id) || "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Duration</p>
                      <p className="font-medium">
                        {formatDuration(selectedCall.call_duration)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Outcome</p>
                      <p className="font-medium">
                        {selectedCall.outcome || "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Interest</p>
                      <p className="font-medium">
                        {selectedCall.metadata?.interest_level ? (
                          <InterestBadge level={selectedCall.metadata.interest_level} />
                        ) : "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Turns</p>
                      <p className="font-medium">
                        {selectedCall.metadata?.call_metrics?.turn_count ?? "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Created</p>
                      <p className="font-medium">
                        {formatDate(selectedCall.created_at)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Started</p>
                      <p className="font-medium">
                        {selectedCall.started_at
                          ? formatDate(selectedCall.started_at)
                          : "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Ended</p>
                      <p className="font-medium">
                        {selectedCall.ended_at
                          ? formatDate(selectedCall.ended_at)
                          : "-"}
                      </p>
                    </div>
                    <div className="col-span-2">
                      <p className="text-muted-foreground">Call SID</p>
                      <p className="font-mono text-xs break-all">
                        {selectedCall.call_sid}
                      </p>
                    </div>
                  </div>

                  {selectedCall.summary && (
                    <>
                      <Separator className="my-4" />
                      <div>
                        <p className="text-sm font-medium mb-2">Summary</p>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {selectedCall.summary}
                        </p>
                      </div>
                    </>
                  )}

                  {/* Goal-based Analytics */}
                  {selectedCall.analytics && (
                    <>
                      <Separator className="my-4" />
                      <div className="space-y-4">
                        <p className="text-sm font-medium flex items-center gap-1.5">
                          <Target className="h-4 w-4 text-violet-500" />
                          Goal Analysis
                        </p>

                        {/* Outcome */}
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">Outcome:</span>
                          <Badge variant="outline" className="capitalize">
                            {(selectedCall.analytics.goal_outcome || "none").replace(/_/g, " ")}
                          </Badge>
                          {selectedCall.analytics.goal_type && (
                            <span className="text-xs text-muted-foreground">
                              ({selectedCall.analytics.goal_type})
                            </span>
                          )}
                        </div>

                        {/* Agent Word Share */}
                        {selectedCall.analytics.agent_word_share != null && (
                          <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground">Agent word share:</span>
                            <span className="text-sm font-medium">
                              {Math.round(selectedCall.analytics.agent_word_share * 100)}%
                            </span>
                          </div>
                        )}

                        {/* Red Flags */}
                        {selectedCall.analytics.has_red_flags && selectedCall.analytics.red_flags && selectedCall.analytics.red_flags.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-sm font-medium flex items-center gap-1.5 text-red-500">
                              <AlertTriangle className="h-3.5 w-3.5" />
                              Red Flags ({selectedCall.analytics.red_flags.length})
                            </p>
                            <div className="space-y-1.5">
                              {selectedCall.analytics.red_flags.map((rf, j) => (
                                <div key={`${rf.id}-${j}`} className="rounded bg-muted/50 p-2 text-xs">
                                  <div className="flex items-center gap-1.5 mb-0.5">
                                    <Badge variant="outline" className={`text-[10px] py-0 ${SEVERITY_COLORS[rf.severity] || ""}`}>
                                      {rf.severity}
                                    </Badge>
                                    <span className="font-medium">{rf.id.replace(/_/g, " ")}</span>
                                  </div>
                                  {rf.evidence && (
                                    <p className="text-muted-foreground italic mt-0.5">
                                      &ldquo;{rf.evidence}&rdquo;
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Captured Data */}
                        {selectedCall.analytics.captured_data && Object.keys(selectedCall.analytics.captured_data).length > 0 && (
                          <div className="space-y-2">
                            <p className="text-sm font-medium flex items-center gap-1.5">
                              <Database className="h-3.5 w-3.5 text-cyan-500" />
                              Captured Data
                            </p>
                            <div className="grid grid-cols-2 gap-2">
                              {Object.entries(selectedCall.analytics.captured_data).map(([key, val]) => (
                                <div key={key} className="rounded bg-muted/50 p-2 text-xs">
                                  <p className="text-muted-foreground capitalize">{key.replace(/_/g, " ")}</p>
                                  <p className="font-medium mt-0.5">{String(val ?? "-")}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                  </ScrollArea>
                </TabsContent>

                {/* Transcript Tab */}
                <TabsContent value="transcript" className="mt-4">
                  <ScrollArea className="h-[400px] rounded-md border">
                    <div className="w-full overflow-hidden">
                      <Table className="table-fixed w-full">
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-10">#</TableHead>
                            <TableHead className="w-16">Speaker</TableHead>
                            <TableHead>Message</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {selectedCall.metadata?.transcript?.map((entry, i) => (
                            <TableRow key={i}>
                              <TableCell className="text-muted-foreground text-xs align-top">
                                {i + 1}
                              </TableCell>
                              <TableCell className="align-top">
                                <Badge
                                  variant={entry.role === "assistant" ? "default" : "secondary"}
                                  className="text-[10px]"
                                >
                                  {entry.role === "assistant" ? "AI" : "User"}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-sm break-words whitespace-normal">
                                {entry.content}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </ScrollArea>
                </TabsContent>

                {/* Recording Tab */}
                <TabsContent value="recording" className="mt-4">
                  <div className="space-y-3 py-2">
                    <audio
                      controls
                      src={getRecordingUrl(selectedCall.call_sid)}
                      preload="none"
                      className="w-full"
                    />
                    <p className="text-xs text-muted-foreground">
                      Stereo recording — Left channel: AI, Right channel: User
                    </p>
                  </div>
                </TabsContent>
              </Tabs>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
