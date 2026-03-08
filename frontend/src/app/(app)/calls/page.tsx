"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Phone,
  PhoneCall,
  Bot,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  FileText,
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
import { Label } from "@/components/ui/label";
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
import { fetchBots, fetchCallLogs, fetchCallDetail, triggerCall, checkHealth, getRecordingUrl } from "@/lib/api";
import { formatDate, formatDuration, formatPhoneNumber, timeAgo, cn } from "@/lib/utils";
import type { BotConfig, CallLog } from "@/types/api";

const STATUS_CONFIG: Record<
  string,
  {
    variant: "default" | "secondary" | "destructive" | "outline";
    icon: typeof Clock;
    color: string;
  }
> = {
  initiated: { variant: "outline", icon: Clock, color: "text-muted-foreground" },
  ringing: { variant: "outline", icon: PhoneCall, color: "text-blue-400" },
  "in-progress": { variant: "default", icon: Activity, color: "text-green-400" },
  completed: { variant: "secondary", icon: CheckCircle2, color: "text-emerald-400" },
  failed: { variant: "destructive", icon: XCircle, color: "text-red-400" },
  error: { variant: "destructive", icon: XCircle, color: "text-red-400" },
  "no-answer": { variant: "secondary", icon: Phone, color: "text-amber-400" },
  busy: { variant: "secondary", icon: Phone, color: "text-amber-400" },
  voicemail: { variant: "secondary", icon: Phone, color: "text-amber-400" },
};

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || {
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

const INTEREST_CONFIG: Record<string, { color: string; label: string }> = {
  high: { color: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20", label: "High" },
  medium: { color: "bg-amber-500/10 text-amber-500 border-amber-500/20", label: "Medium" },
  low: { color: "bg-red-500/10 text-red-500 border-red-500/20", label: "Low" },
};

function InterestBadge({ level }: { level: string }) {
  const config = INTEREST_CONFIG[level];
  if (!config) return <span className="text-muted-foreground">-</span>;
  return (
    <Badge variant="outline" className={cn("text-[10px]", config.color)}>
      {config.label}
    </Badge>
  );
}

const PAGE_SIZE = 20;

export default function CallsPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  // Trigger form
  const [selectedBotId, setSelectedBotId] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [triggering, setTriggering] = useState(false);

  // Filters
  const [filterBotId, setFilterBotId] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(0);

  // Detail modal
  const [selectedCall, setSelectedCall] = useState<CallLog | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadCalls = useCallback(async () => {
    try {
      const data = await fetchCallLogs(
        filterBotId && filterBotId !== "all" ? filterBotId : undefined
      );
      setCalls(data);
    } catch {
      // silent polling
    } finally {
      setLoading(false);
    }
  }, [filterBotId]);

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
    checkHealth()
      .then(() => setHealthOk(true))
      .catch(() => setHealthOk(false));
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

  // Filtered + searched calls
  const filteredCalls = useMemo(() => {
    let result = calls;
    if (filterStatus !== "all") {
      result = result.filter((c) => c.status === filterStatus);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (c) =>
          c.contact_name.toLowerCase().includes(q) ||
          c.contact_phone.includes(q) ||
          (c.summary && c.summary.toLowerCase().includes(q))
      );
    }
    return result;
  }, [calls, filterStatus, searchQuery]);

  const totalPages = Math.ceil(filteredCalls.length / PAGE_SIZE);
  const paginatedCalls = filteredCalls.slice(
    page * PAGE_SIZE,
    (page + 1) * PAGE_SIZE
  );

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [filterBotId, filterStatus, searchQuery]);

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

  async function handleTrigger() {
    if (!selectedBotId || !contactName || !contactPhone) {
      toast.error("Fill in all fields");
      return;
    }
    setTriggering(true);
    try {
      const res = await triggerCall({
        bot_id: selectedBotId,
        contact_name: contactName,
        contact_phone: contactPhone,
      });
      toast.success(`Call queued: ${res.queue_id.slice(0, 8)}...`);
      setContactName("");
      setContactPhone("");
      loadCalls();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger call");
    } finally {
      setTriggering(false);
    }
  }

  const activeBots = bots.filter((b) => b.is_active).length;
  const activeCalls = calls.filter((c) =>
    ["initiated", "ringing", "in-progress"].includes(c.status)
  ).length;

  return (
    <>
      <Header title="Calls" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Stats bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { icon: Bot, label: "Active Bots", value: activeBots, gradient: "from-violet-500 to-indigo-500" },
              { icon: Phone, label: "Total Calls", value: calls.length, gradient: "from-emerald-500 to-green-500" },
              { icon: Activity, label: "Active Now", value: activeCalls, gradient: "from-amber-500 to-orange-500" },
              { icon: Activity, label: "API Health", value: healthOk === null ? "..." : healthOk ? "OK" : "Down", gradient: "from-rose-500 to-pink-500" },
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

          {/* Trigger call form */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Trigger Call</CardTitle>
              <CardDescription>Start an outbound call to a contact</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>Bot</Label>
                  <Select value={selectedBotId} onValueChange={setSelectedBotId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select bot..." />
                    </SelectTrigger>
                    <SelectContent>
                      {bots.filter((b) => b.is_active).map((bot) => (
                        <SelectItem key={bot.id} value={bot.id}>
                          {bot.agent_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Contact Name</Label>
                  <Input
                    value={contactName}
                    onChange={(e) => setContactName(e.target.value)}
                    placeholder="John Doe"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Phone</Label>
                  <Input
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    placeholder="+919052034075"
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    onClick={handleTrigger}
                    disabled={triggering}
                    className="w-full"
                  >
                    {triggering ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <PhoneCall className="mr-2 h-4 w-4" />
                    )}
                    {triggering ? "Calling..." : "Trigger"}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Call logs with filters */}
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <CardTitle className="text-base">Call History</CardTitle>
                  <CardDescription>
                    {filteredCalls.length} call{filteredCalls.length !== 1 ? "s" : ""}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
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
                    <SelectTrigger className="w-36">
                      <SelectValue placeholder="All statuses" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All statuses</SelectItem>
                      {Object.keys(STATUS_CONFIG).map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
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
                  <Phone className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm">No calls found</p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Status</TableHead>
                        <TableHead>Contact</TableHead>
                        <TableHead>Phone</TableHead>
                        <TableHead>Duration</TableHead>
                        <TableHead>Outcome</TableHead>
                        <TableHead>Summary</TableHead>
                        <TableHead>Time</TableHead>
                        <TableHead className="w-10"></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {paginatedCalls.map((call) => (
                        <TableRow
                          key={call.id}
                          className="cursor-pointer"
                          onClick={() => openCallDetail(call)}
                        >
                          <TableCell>
                            <StatusBadge status={call.status} />
                          </TableCell>
                          <TableCell className="font-medium">
                            {call.contact_name}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {formatPhoneNumber(call.contact_phone)}
                          </TableCell>
                          <TableCell>
                            {formatDuration(call.call_duration)}
                          </TableCell>
                          <TableCell>
                            {call.outcome && (
                              <Badge variant="outline">{call.outcome}</Badge>
                            )}
                          </TableCell>
                          <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">
                            {call.summary || "-"}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                            {timeAgo(call.created_at)}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={(e) => {
                                e.stopPropagation();
                                openCallDetail(call);
                              }}
                            >
                              <FileText className="h-3.5 w-3.5" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
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

      {/* Call Detail Modal */}
      <Dialog
        open={!!selectedCall}
        onOpenChange={(open) => !open && setSelectedCall(null)}
      >
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto overflow-x-hidden">
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

                <TabsContent value="details" className="mt-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
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
                </TabsContent>

                <TabsContent value="transcript" className="mt-4">
                  <div className="max-h-[400px] overflow-y-auto overflow-x-hidden rounded-md border">
                    <Table className="table-fixed w-full">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10">#</TableHead>
                          <TableHead className="w-20">Speaker</TableHead>
                          <TableHead>Message</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {selectedCall.metadata?.transcript?.map((entry, i) => (
                          <TableRow key={i}>
                            <TableCell className="text-muted-foreground text-xs">
                              {i + 1}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={entry.role === "assistant" ? "default" : "secondary"}
                                className="text-[10px]"
                              >
                                {entry.role === "assistant" ? "AI" : "User"}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-sm break-words">
                              {entry.content}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </TabsContent>

                <TabsContent value="recording" className="mt-4">
                  <div className="space-y-3 py-2">
                    <audio
                      controls
                      src={getRecordingUrl(selectedCall.call_sid)}
                      preload="none"
                      className="w-full"
                    />
                    <p className="text-xs text-muted-foreground">
                      Call recording — AI + User mixed
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
