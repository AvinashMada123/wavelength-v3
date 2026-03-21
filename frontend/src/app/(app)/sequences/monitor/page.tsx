"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Activity,
  Pause,
  Play,
  XCircle,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  RefreshCw,
  Loader2,
  AlertTriangle,
  SkipForward,
} from "lucide-react";
import { toast } from "sonner";
import { format, formatDistanceToNow } from "date-fns";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
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
  fetchInstances,
  fetchInstance,
  fetchTemplates,
  pauseInstance,
  resumeInstance,
  cancelInstance,
  advanceInstance,
  type SequenceInstance,
  type SequenceTouchpoint,
  type SequenceTemplate,
} from "@/lib/sequences-api";
import { TouchpointTimeline } from "../components/TouchpointTimeline";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 30_000;

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const INSTANCE_STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  active: {
    label: "Active",
    className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  },
  completed: {
    label: "Completed",
    className: "bg-green-500/10 text-green-400 border-green-500/20",
  },
  paused: {
    label: "Paused",
    className: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
  },
  failed: {
    label: "Failed",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
  },
};

function InstanceStatusBadge({ status }: { status: string }) {
  const config =
    INSTANCE_STATUS_CONFIG[status] ?? INSTANCE_STATUS_CONFIG.active;
  return (
    <Badge variant="outline" className={`text-xs ${config.className}`}>
      {config.label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Expanded row
// ---------------------------------------------------------------------------

interface ExpandedRowProps {
  instanceId: string;
}

function ExpandedRow({ instanceId }: ExpandedRowProps) {
  const [touchpoints, setTouchpoints] = useState<SequenceTouchpoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchInstance(instanceId)
      .then((data) => {
        if (!cancelled) setTouchpoints(data.touchpoints ?? []);
      })
      .catch(() => {
        if (!cancelled) toast.error("Failed to load touchpoints");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [instanceId]);

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div className="px-4 pb-4 pt-2">
      <TouchpointTimeline touchpoints={touchpoints} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nav links
// ---------------------------------------------------------------------------

const NAV_LINKS = [
  { href: "/sequences", label: "Templates" },
  { href: "/sequences/monitor", label: "Monitor" },
  { href: "/sequences/analytics", label: "Analytics" },
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function EngagementMonitorPage() {
  const [instances, setInstances] = useState<SequenceInstance[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  // Filters
  const [templateFilter, setTemplateFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Templates for dropdown
  const [templates, setTemplates] = useState<SequenceTemplate[]>([]);

  // Auto-refresh
  const [autoRefresh, setAutoRefresh] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Expanded row
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Per-row action loading
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>(
    {}
  );

  // ---------------------------------------------------------------------------
  // Load templates for filter dropdown
  // ---------------------------------------------------------------------------

  useEffect(() => {
    fetchTemplates(1, 100)
      .then((data) => setTemplates(data.items))
      .catch(() => {});
  }, []);

  // ---------------------------------------------------------------------------
  // Load instances
  // ---------------------------------------------------------------------------

  const loadInstances = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchInstances({
        template_id: templateFilter === "all" ? undefined : templateFilter,
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
      });
      setInstances(data.items);
      setTotal(data.total);
    } catch {
      toast.error("Failed to load engagement instances");
    } finally {
      setLoading(false);
    }
  }, [templateFilter, statusFilter, page]);

  useEffect(() => {
    loadInstances();
  }, [loadInstances]);

  // ---------------------------------------------------------------------------
  // Auto-refresh
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        loadInstances();
      }, POLL_INTERVAL_MS);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, loadInstances]);

  // ---------------------------------------------------------------------------
  // Row actions
  // ---------------------------------------------------------------------------

  async function handleAction(
    id: string,
    action: "pause" | "resume" | "cancel" | "advance"
  ) {
    setActionLoading((prev) => ({ ...prev, [id]: true }));
    try {
      if (action === "pause") await pauseInstance(id);
      else if (action === "resume") await resumeInstance(id);
      else if (action === "advance") {
        const result = await advanceInstance(id);
        toast.success(`Advanced: Step ${result.step_order} "${result.step_name}" → ${result.status}`);
        // Refresh expanded row if open
        if (expandedId === id) {
          setExpandedId(null);
          setTimeout(() => setExpandedId(id), 100);
        }
      } else await cancelInstance(id);
      if (action !== "advance") {
        toast.success(
          action === "pause"
            ? "Instance paused"
            : action === "resume"
              ? "Instance resumed"
              : "Instance cancelled"
        );
      }
      loadInstances();
    } catch (err: any) {
      const detail = err?.message || `Failed to ${action} instance`;
      toast.error(detail);
    } finally {
      setActionLoading((prev) => ({ ...prev, [id]: false }));
    }
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function failedTouchpointCount(instance: SequenceInstance): number {
    // We don't have touchpoints in the list view, so we surface via context_data if available
    const ctx = instance.context_data ?? {};
    return typeof ctx.failed_touchpoints === "number"
      ? ctx.failed_touchpoints
      : 0;
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      <Header title="Engagement Monitor" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Nav links */}
          <div className="flex items-center gap-1 border-b border-border pb-3">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href}>
                <Button
                  variant={
                    link.href === "/sequences/monitor" ? "secondary" : "ghost"
                  }
                  size="sm"
                >
                  {link.label}
                </Button>
              </Link>
            ))}
          </div>

          {/* Description + auto-refresh */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              Track active and historical engagement sequences per lead
            </p>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Switch
                  id="auto-refresh"
                  checked={autoRefresh}
                  onCheckedChange={setAutoRefresh}
                />
                <Label htmlFor="auto-refresh" className="text-sm cursor-pointer">
                  Auto-refresh (30s)
                </Label>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={loadInstances}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Refresh
              </Button>
            </div>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={templateFilter}
              onValueChange={(v) => {
                setTemplateFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-9 w-52">
                <SelectValue placeholder="All Templates" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Templates</SelectItem>
                {templates.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={statusFilter}
              onValueChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-9 w-40">
                <SelectValue placeholder="All Statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="paused">Paused</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Table */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="space-y-3 p-6">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : instances.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Activity className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm font-medium">No engagement instances found</p>
                  <p className="mt-1 text-xs">
                    Instances appear here when sequences are triggered for leads
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8" />
                      <TableHead>Lead</TableHead>
                      <TableHead>Template</TableHead>
                      <TableHead>Progress</TableHead>
                      <TableHead>Next Touchpoint</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Started</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {instances.map((instance) => {
                      const isExpanded = expandedId === instance.id;
                      const isActing = actionLoading[instance.id] ?? false;
                      const failedCount = failedTouchpointCount(instance);

                      return (
                        <>
                          <TableRow
                            key={instance.id}
                            className="cursor-pointer hover:bg-muted/50"
                            onClick={() => toggleExpand(instance.id)}
                          >
                            {/* Expand icon */}
                            <TableCell className="pr-0">
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                              )}
                            </TableCell>

                            {/* Lead */}
                            <TableCell>
                              <div className="min-w-0">
                                <p className="font-medium truncate max-w-[140px]">
                                  {instance.lead_name ?? "Unknown Lead"}
                                </p>
                                {instance.lead_phone && (
                                  <p className="text-xs text-muted-foreground">
                                    {instance.lead_phone}
                                  </p>
                                )}
                              </div>
                            </TableCell>

                            {/* Template */}
                            <TableCell>
                              <span className="text-sm truncate max-w-[140px] block">
                                {instance.template_name ?? "—"}
                              </span>
                            </TableCell>

                            {/* Progress */}
                            <TableCell>
                              <div className="flex items-center gap-1.5">
                                <span className="text-sm tabular-nums">
                                  {instance.current_step ?? "—"}
                                </span>
                                {failedCount > 0 && (
                                  <Badge
                                    variant="outline"
                                    className="h-5 gap-1 bg-red-500/10 text-red-400 border-red-500/20 text-xs"
                                  >
                                    <AlertTriangle className="h-3 w-3" />
                                    {failedCount} failed
                                  </Badge>
                                )}
                              </div>
                            </TableCell>

                            {/* Next touchpoint */}
                            <TableCell>
                              {instance.next_touchpoint_at ? (
                                <span className="text-xs text-muted-foreground">
                                  {formatDistanceToNow(
                                    new Date(instance.next_touchpoint_at),
                                    { addSuffix: true }
                                  )}
                                </span>
                              ) : (
                                <span className="text-xs text-muted-foreground">—</span>
                              )}
                            </TableCell>

                            {/* Status */}
                            <TableCell>
                              <InstanceStatusBadge status={instance.status} />
                            </TableCell>

                            {/* Started */}
                            <TableCell className="text-xs text-muted-foreground">
                              {format(
                                new Date(instance.started_at),
                                "MMM d, yyyy"
                              )}
                            </TableCell>

                            {/* Actions */}
                            <TableCell>
                              <div
                                className="flex items-center justify-end gap-1"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {(instance.status === "active" || instance.status === "paused") && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-muted-foreground hover:text-violet-400"
                                    disabled={isActing}
                                    title="Advance to next step"
                                    onClick={() =>
                                      handleAction(instance.id, "advance")
                                    }
                                  >
                                    {isActing ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    ) : (
                                      <SkipForward className="h-3.5 w-3.5" />
                                    )}
                                  </Button>
                                )}
                                {instance.status === "active" && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-muted-foreground hover:text-yellow-400"
                                    disabled={isActing}
                                    title="Pause"
                                    onClick={() =>
                                      handleAction(instance.id, "pause")
                                    }
                                  >
                                    {isActing ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    ) : (
                                      <Pause className="h-3.5 w-3.5" />
                                    )}
                                  </Button>
                                )}
                                {instance.status === "paused" && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-muted-foreground hover:text-blue-400"
                                    disabled={isActing}
                                    title="Resume"
                                    onClick={() =>
                                      handleAction(instance.id, "resume")
                                    }
                                  >
                                    {isActing ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    ) : (
                                      <Play className="h-3.5 w-3.5" />
                                    )}
                                  </Button>
                                )}
                                {(instance.status === "active" ||
                                  instance.status === "paused") && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                                    disabled={isActing}
                                    title="Cancel"
                                    onClick={() =>
                                      handleAction(instance.id, "cancel")
                                    }
                                  >
                                    <XCircle className="h-3.5 w-3.5" />
                                  </Button>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>

                          {/* Inline expanded timeline */}
                          {isExpanded && (
                            <TableRow key={`${instance.id}-expanded`}>
                              <TableCell
                                colSpan={8}
                                className="bg-muted/30 p-0"
                              >
                                <ExpandedRow instanceId={instance.id} />
                              </TableCell>
                            </TableRow>
                          )}
                        </>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Pagination */}
          {!loading && instances.length > 0 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * PAGE_SIZE + 1}&ndash;
                {Math.min(page * PAGE_SIZE, total)} of {total} instances
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {page} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
