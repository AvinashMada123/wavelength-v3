"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Megaphone,
  Plus,
  Loader2,
  Play,
  Pause,
  XCircle,
  ChevronLeft,
  ChevronRight,
  Search,
  Clock,
  CheckCircle2,
  AlertCircle,
  Ban,
  FileEdit,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  fetchCampaigns,
  createCampaign,
  getCampaign,
  startCampaign,
  pauseCampaign,
  cancelCampaign,
  fetchBots,
  fetchLeads,
  type Campaign,
  type Lead,
} from "@/lib/api";
import { CAMPAIGN_STATUS_CONFIG } from "@/lib/status-config";
import { DateRangePicker, type DateRange } from "@/components/date-range-picker";
import type { BotConfig } from "@/types/api";

const PAGE_SIZE = 10;

function StatusBadge({ status }: { status: string }) {
  const config = CAMPAIGN_STATUS_CONFIG[status] || CAMPAIGN_STATUS_CONFIG.draft;
  const Icon = config.icon;
  return (
    <Badge variant="outline" className={`gap-1 ${config.className}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </Badge>
  );
}

export default function CampaignsPage() {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateRange, setDateRange] = useState<DateRange>({ from: null, to: null });
  const [loading, setLoading] = useState(true);

  // Detail view
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formName, setFormName] = useState("");
  const [formBotId, setFormBotId] = useState("");
  const [formConcurrency, setFormConcurrency] = useState("3");
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [leadSearch, setLeadSearch] = useState("");

  // Data for create form
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [botsLoading, setBotsLoading] = useState(false);
  const [leadsLoading, setLeadsLoading] = useState(false);

  // Client-side date filtering
  const filteredCampaigns = useMemo(() => {
    if (!dateRange.from && !dateRange.to) return campaigns;
    return campaigns.filter((c) => {
      const d = c.created_at.slice(0, 10);
      if (dateRange.from && d < dateRange.from) return false;
      if (dateRange.to && d > dateRange.to) return false;
      return true;
    });
  }, [campaigns, dateRange]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const loadCampaigns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCampaigns({
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
        page_size: PAGE_SIZE,
      });
      setCampaigns(data.items);
      setTotal(data.total);
    } catch (err) {
      toast.error("Failed to load campaigns");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, page]);

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  // Load bots when create dialog opens
  useEffect(() => {
    if (!createOpen) return;
    setBotsLoading(true);
    fetchBots()
      .then(setBots)
      .catch(() => toast.error("Failed to load bots"))
      .finally(() => setBotsLoading(false));
    // Load initial leads (first page)
    setLeadsLoading(true);
    fetchLeads({ page_size: 30 })
      .then((data) => setLeads(data.items))
      .catch(() => toast.error("Failed to load leads"))
      .finally(() => setLeadsLoading(false));
  }, [createOpen]);

  // Debounced lead search for campaign create dialog
  const leadSearchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!createOpen) return;
    if (leadSearchTimerRef.current) clearTimeout(leadSearchTimerRef.current);
    leadSearchTimerRef.current = setTimeout(async () => {
      setLeadsLoading(true);
      try {
        const data = await fetchLeads({
          search: leadSearch || undefined,
          page_size: 30,
        });
        setLeads(data.items);
      } catch {
        // keep existing leads on error
      } finally {
        setLeadsLoading(false);
      }
    }, 300);
    return () => {
      if (leadSearchTimerRef.current) clearTimeout(leadSearchTimerRef.current);
    };
  }, [leadSearch, createOpen]);

  async function handleCreate() {
    if (!formName.trim()) {
      toast.error("Campaign name is required");
      return;
    }
    if (!formBotId) {
      toast.error("Please select a bot");
      return;
    }
    if (selectedLeadIds.size === 0) {
      toast.error("Please select at least one lead");
      return;
    }
    const concurrency = parseInt(formConcurrency, 10);
    if (isNaN(concurrency) || concurrency < 1) {
      toast.error("Concurrency limit must be at least 1");
      return;
    }

    setCreating(true);
    try {
      await createCampaign({
        name: formName.trim(),
        bot_config_id: formBotId,
        lead_ids: Array.from(selectedLeadIds),
        concurrency_limit: concurrency,
      });
      toast.success("Campaign created successfully");
      setCreateOpen(false);
      resetForm();
      loadCampaigns();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create campaign";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  }

  function resetForm() {
    setFormName("");
    setFormBotId("");
    setFormConcurrency("3");
    setSelectedLeadIds(new Set());
    setLeadSearch("");
  }

  async function handleSelectCampaign(campaign: Campaign) {
    if (selectedCampaign?.id === campaign.id) {
      setSelectedCampaign(null);
      return;
    }
    setDetailLoading(true);
    try {
      const detail = await getCampaign(campaign.id);
      setSelectedCampaign(detail);
    } catch {
      toast.error("Failed to load campaign details");
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleAction(action: "start" | "pause" | "cancel") {
    if (!selectedCampaign) return;
    setActionLoading(true);
    try {
      let updated: Campaign;
      switch (action) {
        case "start":
          updated = await startCampaign(selectedCampaign.id);
          toast.success("Campaign started");
          break;
        case "pause":
          updated = await pauseCampaign(selectedCampaign.id);
          toast.success("Campaign paused");
          break;
        case "cancel":
          updated = await cancelCampaign(selectedCampaign.id);
          toast.success("Campaign cancelled");
          break;
      }
      setSelectedCampaign(updated!);
      loadCampaigns();
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to ${action} campaign`;
      toast.error(message);
    } finally {
      setActionLoading(false);
    }
  }

  function toggleLead(leadId: string) {
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      if (next.has(leadId)) {
        next.delete(leadId);
      } else {
        next.add(leadId);
      }
      return next;
    });
  }

  function toggleAllFilteredLeads() {
    const filtered = filteredLeads;
    const allSelected = filtered.every((l) => selectedLeadIds.has(l.id));
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        filtered.forEach((l) => next.delete(l.id));
      } else {
        filtered.forEach((l) => next.add(l.id));
      }
      return next;
    });
  }

  // Leads are now fetched server-side with search param, no client-side filtering needed
  const filteredLeads = leads;

  const botsMap = new Map<string, string>();
  bots.forEach((b) => botsMap.set(b.id, b.agent_name));

  return (
    <>
      <Header title="Campaigns" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Page description */}
          <div>
            <p className="text-sm text-muted-foreground">
              Create and manage outbound calling campaigns
            </p>
          </div>

          {/* Top bar: Filter + Create */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Select
              value={statusFilter}
              onValueChange={(v) => {
                setStatusFilter(v);
                setPage(1);
                setSelectedCampaign(null);
              }}
            >
              <SelectTrigger className="w-full sm:w-48">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="paused">Paused</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
              </SelectContent>
            </Select>
              <DateRangePicker value={dateRange} onChange={setDateRange} />

            <Dialog
              open={createOpen}
              onOpenChange={(open) => {
                setCreateOpen(open);
                if (!open) resetForm();
              }}
            >
              <DialogTrigger asChild>
                <Button className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
                  <Plus className="h-4 w-4" />
                  New Campaign
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle>Create Campaign</DialogTitle>
                  <DialogDescription>
                    Set up a new outbound calling campaign
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                  {/* Campaign Name */}
                  <div className="space-y-2">
                    <Label htmlFor="campaignName">Campaign Name</Label>
                    <Input
                      id="campaignName"
                      placeholder="e.g. Q1 Outreach"
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      disabled={creating}
                    />
                  </div>

                  {/* Bot Selector */}
                  <div className="space-y-2">
                    <Label>Bot Configuration</Label>
                    {botsLoading ? (
                      <Skeleton className="h-9 w-full" />
                    ) : (
                      <Select value={formBotId} onValueChange={setFormBotId}>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="Select a bot" />
                        </SelectTrigger>
                        <SelectContent>
                          {bots.map((bot) => (
                            <SelectItem key={bot.id} value={bot.id}>
                              {bot.agent_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>

                  {/* Lead Selection */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>
                        Leads{" "}
                        <span className="text-muted-foreground font-normal">
                          ({selectedLeadIds.size} selected)
                        </span>
                      </Label>
                      {filteredLeads.length > 0 && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={toggleAllFilteredLeads}
                        >
                          {filteredLeads.every((l) => selectedLeadIds.has(l.id))
                            ? "Deselect All"
                            : "Select All"}
                        </Button>
                      )}
                    </div>
                    <div className="relative">
                      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        placeholder="Search leads..."
                        className="pl-8"
                        value={leadSearch}
                        onChange={(e) => setLeadSearch(e.target.value)}
                      />
                    </div>
                    {leadsLoading ? (
                      <div className="space-y-2">
                        {Array.from({ length: 3 }).map((_, i) => (
                          <Skeleton key={i} className="h-10 w-full" />
                        ))}
                      </div>
                    ) : filteredLeads.length === 0 ? (
                      <p className="py-4 text-center text-sm text-muted-foreground">
                        No leads found
                      </p>
                    ) : (
                      <ScrollArea className="h-48 rounded-md border">
                        <div className="p-1">
                          {filteredLeads.map((lead) => {
                            const isChecked = selectedLeadIds.has(lead.id);
                            return (
                              <button
                                key={lead.id}
                                type="button"
                                onClick={() => toggleLead(lead.id)}
                                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50 ${
                                  isChecked ? "bg-violet-500/10" : ""
                                }`}
                              >
                                <div
                                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border transition-colors ${
                                    isChecked
                                      ? "border-violet-500 bg-violet-500 text-white"
                                      : "border-muted-foreground/30"
                                  }`}
                                >
                                  {isChecked && (
                                    <CheckCircle2 className="h-3 w-3" />
                                  )}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <p className="truncate font-medium">
                                    {lead.contact_name}
                                  </p>
                                  <p className="truncate text-xs text-muted-foreground">
                                    {lead.phone_number}
                                    {lead.company ? ` - ${lead.company}` : ""}
                                  </p>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </ScrollArea>
                    )}
                  </div>

                  {/* Concurrency Limit */}
                  <div className="space-y-2">
                    <Label htmlFor="concurrency">Concurrency Limit</Label>
                    <Input
                      id="concurrency"
                      type="number"
                      min={1}
                      max={50}
                      value={formConcurrency}
                      onChange={(e) => setFormConcurrency(e.target.value)}
                      disabled={creating}
                    />
                    <p className="text-xs text-muted-foreground">
                      Maximum number of simultaneous calls
                    </p>
                  </div>
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => setCreateOpen(false)}
                    disabled={creating}
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleCreate}
                    disabled={creating}
                    className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                  >
                    {creating ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      "Create Campaign"
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>

          {/* Campaign List */}
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : filteredCampaigns.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted mb-4">
                  <Megaphone className="h-7 w-7 text-muted-foreground" />
                </div>
                <h2 className="text-lg font-semibold">No campaigns yet</h2>
                <p className="mt-1 text-sm text-muted-foreground text-center max-w-sm">
                  Create your first campaign to start making outbound calls at
                  scale.
                </p>
                <Button
                  className="mt-4 bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  New Campaign
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {filteredCampaigns.map((campaign, i) => {
                const resolvedLeads = campaign.completed_leads + campaign.failed_leads;
                const progressPct =
                  campaign.total_leads > 0
                    ? Math.round(
                        (resolvedLeads / campaign.total_leads) * 100
                      )
                    : 0;
                const isSelected = selectedCampaign?.id === campaign.id;

                return (
                  <motion.div
                    key={campaign.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                  >
                    <Card
                      className={`cursor-pointer transition-colors hover:border-violet-500/30 ${
                        isSelected ? "border-violet-500/50 ring-1 ring-violet-500/20" : ""
                      }`}
                      onClick={() => handleSelectCampaign(campaign)}
                    >
                      <CardContent className="pt-6">
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-3">
                              <h3 className="truncate text-sm font-semibold">
                                {campaign.name}
                              </h3>
                              <StatusBadge status={campaign.status} />
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                              <span>
                                {resolvedLeads}/{campaign.total_leads}{" "}
                                leads processed
                              </span>
                              {campaign.total_leads > 0 && (
                                <span className="text-blue-400">
                                  {Math.round(
                                    (campaign.completed_leads /
                                      campaign.total_leads) *
                                      100
                                  )}% connected
                                </span>
                              )}
                              {campaign.failed_leads > 0 && (
                                <span className="text-red-400">
                                  {campaign.failed_leads} failed
                                </span>
                              )}
                              <span>
                                Created{" "}
                                {format(new Date(campaign.created_at), "MMM d, yyyy")}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-3 sm:w-56">
                            <Progress value={progressPct} className="flex-1" />
                            <span className="text-xs font-medium text-muted-foreground w-10 text-right">
                              {progressPct}%
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
                              onClick={(e) => {
                                e.stopPropagation();
                                router.push(`/campaigns/${campaign.id}`);
                              }}
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>

                        {/* Detail Panel */}
                        {isSelected && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            transition={{ duration: 0.25 }}
                            className="mt-4 border-t pt-4"
                          >
                            {detailLoading ? (
                              <div className="space-y-3">
                                <Skeleton className="h-8 w-48" />
                                <Skeleton className="h-20 w-full" />
                              </div>
                            ) : (
                              <div className="space-y-4">
                                {/* Action Buttons */}
                                <div className="flex flex-wrap items-center gap-2">
                                  {(selectedCampaign.status === "draft" ||
                                    selectedCampaign.status === "paused") && (
                                    <Button
                                      size="sm"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleAction("start");
                                      }}
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
                                  {selectedCampaign.status === "running" && (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleAction("pause");
                                      }}
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
                                  {(selectedCampaign.status === "draft" ||
                                    selectedCampaign.status === "running" ||
                                    selectedCampaign.status === "paused") && (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleAction("cancel");
                                      }}
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
                                  {selectedCampaign.status === "completed" && (
                                    <span className="flex items-center gap-1.5 text-sm text-green-400">
                                      <CheckCircle2 className="h-4 w-4" />
                                      Campaign completed
                                    </span>
                                  )}
                                  {selectedCampaign.status === "cancelled" && (
                                    <span className="flex items-center gap-1.5 text-sm text-red-400">
                                      <Ban className="h-4 w-4" />
                                      Campaign cancelled
                                    </span>
                                  )}
                                </div>

                                {/* Detail Info Grid */}
                                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                                  <div>
                                    <p className="text-xs text-muted-foreground">
                                      Total Leads
                                    </p>
                                    <p className="text-lg font-semibold">
                                      {selectedCampaign.total_leads}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-muted-foreground">
                                      Completed
                                    </p>
                                    <p className="text-lg font-semibold text-green-400">
                                      {selectedCampaign.completed_leads}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-muted-foreground">
                                      Failed
                                    </p>
                                    <p className="text-lg font-semibold text-red-400">
                                      {selectedCampaign.failed_leads}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-muted-foreground">
                                      Concurrency
                                    </p>
                                    <p className="text-lg font-semibold">
                                      {selectedCampaign.concurrency_limit}
                                    </p>
                                  </div>
                                </div>

                                {/* Progress bar */}
                                <div>
                                  <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                                    <span>Progress</span>
                                    <span>
                                      {resolvedLeads}/
                                      {selectedCampaign.total_leads} (
                                      {progressPct}%)
                                    </span>
                                  </div>
                                  <Progress value={progressPct} className="h-3" />
                                </div>

                                {/* Lead Status Breakdown */}
                                {selectedCampaign.lead_status_breakdown &&
                                  Object.keys(
                                    selectedCampaign.lead_status_breakdown
                                  ).length > 0 && (
                                    <div>
                                      <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                                        Lead Status Breakdown
                                      </p>
                                      <div className="flex flex-wrap gap-2">
                                        {Object.entries(
                                          selectedCampaign.lead_status_breakdown
                                        ).map(([status, count]) => (
                                          <div
                                            key={status}
                                            className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm"
                                          >
                                            <span className="capitalize text-muted-foreground">
                                              {status.replace(/_/g, " ")}
                                            </span>
                                            <span className="font-semibold">
                                              {count}
                                            </span>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                {/* Timestamps */}
                                <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                                  {selectedCampaign.started_at && (
                                    <span>
                                      Started:{" "}
                                      {format(
                                        new Date(selectedCampaign.started_at),
                                        "MMM d, yyyy h:mm a"
                                      )}
                                    </span>
                                  )}
                                  {selectedCampaign.completed_at && (
                                    <span>
                                      Completed:{" "}
                                      {format(
                                        new Date(selectedCampaign.completed_at),
                                        "MMM d, yyyy h:mm a"
                                      )}
                                    </span>
                                  )}
                                </div>
                              </div>
                            )}
                          </motion.div>
                        )}
                      </CardContent>
                    </Card>
                  </motion.div>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * PAGE_SIZE + 1}-
                {Math.min(page * PAGE_SIZE, total)} of {total}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => {
                    setPage((p) => p - 1);
                    setSelectedCampaign(null);
                  }}
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
                  onClick={() => {
                    setPage((p) => p + 1);
                    setSelectedCampaign(null);
                  }}
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
