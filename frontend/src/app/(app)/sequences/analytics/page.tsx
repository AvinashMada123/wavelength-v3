"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  RefreshCw,
  BarChart3,
} from "lucide-react";
import { format, subDays } from "date-fns";
import { toast } from "sonner";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
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
  fetchTemplates,
  fetchAnalyticsOverview,
  fetchAnalyticsChannels,
  fetchAnalyticsTemplates,
  fetchAnalyticsLeads,
  fetchAnalyticsFailures,
  fetchAnalyticsFunnel,
  fetchAnalyticsLeadDetail,
  type SequenceTemplate,
  type AnalyticsFilters,
  type AnalyticsOverview,
  type ChannelStats,
  type TemplateStats,
  type LeadsData,
  type FailuresData,
  type FunnelData,
  type LeadDetail,
} from "@/lib/sequences-api";
import { AnalyticsDrillDown } from "@/components/sequences/AnalyticsDrillDown";

// ---------------------------------------------------------------------------
// Nav links
// ---------------------------------------------------------------------------

const NAV_LINKS = [
  { href: "/sequences", label: "Templates" },
  { href: "/sequences/monitor", label: "Monitor" },
  { href: "/sequences/analytics", label: "Analytics" },
];

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

function KPICard({
  label,
  value,
  trend,
  fmt,
}: {
  label: string;
  value: number | null;
  trend: number | null;
  fmt?: "percent" | "hours" | "number";
}) {
  const formatted =
    value === null
      ? "\u2014"
      : fmt === "percent"
        ? `${(value * 100).toFixed(1)}%`
        : fmt === "hours"
          ? `${value}h`
          : value.toLocaleString();

  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">
          {label}
        </p>
        <p className="text-2xl font-bold mt-1">{formatted}</p>
        <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground">
          {trend === null ? (
            <Minus className="h-3 w-3" />
          ) : trend > 0 ? (
            <TrendingUp className="h-3 w-3 text-green-500" />
          ) : trend < 0 ? (
            <TrendingDown className="h-3 w-3 text-red-500" />
          ) : (
            <Minus className="h-3 w-3" />
          )}
          <span>
            {trend === null
              ? "\u2014"
              : `${trend > 0 ? "+" : ""}${(trend * 100).toFixed(1)}%`}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tier badge
// ---------------------------------------------------------------------------

const TIER_CONFIG: Record<string, { label: string; className: string }> = {
  hot: { label: "Hot", className: "bg-green-500/20 text-green-400" },
  warm: { label: "Warm", className: "bg-yellow-500/20 text-yellow-400" },
  cold: { label: "Cold", className: "bg-blue-500/20 text-blue-400" },
  inactive: {
    label: "Inactive",
    className: "bg-gray-500/20 text-gray-400",
  },
};

function TierBadge({ tier }: { tier: string }) {
  const config = TIER_CONFIG[tier] ?? TIER_CONFIG.inactive;
  return <Badge className={config.className}>{config.label}</Badge>;
}

// ---------------------------------------------------------------------------
// Channel label
// ---------------------------------------------------------------------------

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp_template: "WhatsApp Template",
  whatsapp_session: "WhatsApp Session",
  sms: "SMS",
  voice_call: "Voice Call",
  webhook: "Webhook",
};

// ---------------------------------------------------------------------------
// Mini Funnel (CSS-only)
// ---------------------------------------------------------------------------

function MiniFunnel({ values }: { values: number[] }) {
  if (!values.length) return <span className="text-muted-foreground">\u2014</span>;
  const max = Math.max(...values, 1);
  return (
    <div className="flex items-end gap-0.5 h-5">
      {values.map((v, i) => (
        <div
          key={i}
          className="w-2 bg-violet-500/70 rounded-sm"
          style={{ height: `${Math.max((v / max) * 100, 8)}%` }}
          title={`Step ${i + 1}: ${v}`}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preset buttons
// ---------------------------------------------------------------------------

const DATE_PRESETS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: null },
] as const;

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SequenceAnalyticsPage() {
  // Filters
  const [filters, setFilters] = useState<AnalyticsFilters>({});
  const [activePreset, setActivePreset] = useState<string>("All");

  // Data
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [channels, setChannels] = useState<ChannelStats[]>([]);
  const [templates, setTemplates] = useState<TemplateStats[]>([]);
  const [leads, setLeads] = useState<LeadsData | null>(null);
  const [failures, setFailures] = useState<FailuresData | null>(null);
  const [loading, setLoading] = useState(true);

  // Template dropdown options
  const [templateOptions, setTemplateOptions] = useState<SequenceTemplate[]>(
    []
  );

  // Drill-down state
  const [drillDown, setDrillDown] = useState<{
    type: "template" | "lead";
    id: string;
  } | null>(null);
  const [funnelData, setFunnelData] = useState<FunnelData | null>(null);
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);

  // Sort state for template table
  const [sortCol, setSortCol] = useState<string>("total_sent");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // ---------------------------------------------------------------------------
  // Load template options for filter dropdown
  // ---------------------------------------------------------------------------

  useEffect(() => {
    fetchTemplates(1, 100)
      .then((data) => setTemplateOptions(data.items))
      .catch(() => {});
  }, []);

  // ---------------------------------------------------------------------------
  // Load analytics data
  // ---------------------------------------------------------------------------

  const loadData = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      fetchAnalyticsOverview(filters),
      fetchAnalyticsChannels(filters),
      fetchAnalyticsTemplates(filters),
      fetchAnalyticsLeads(filters),
      fetchAnalyticsFailures(filters),
    ]);
    if (results[0].status === "fulfilled") setOverview(results[0].value);
    if (results[1].status === "fulfilled")
      setChannels(results[1].value.channels);
    if (results[2].status === "fulfilled")
      setTemplates(results[2].value.templates);
    if (results[3].status === "fulfilled") setLeads(results[3].value);
    if (results[4].status === "fulfilled") setFailures(results[4].value);
    setLoading(false);
  }, [filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ---------------------------------------------------------------------------
  // Preset handler
  // ---------------------------------------------------------------------------

  const setPreset = (days: number | null, label: string) => {
    setActivePreset(label);
    if (days === null) {
      setFilters((f) => ({ ...f, start_date: undefined, end_date: undefined }));
    } else {
      const end = format(new Date(), "yyyy-MM-dd");
      const start = format(subDays(new Date(), days), "yyyy-MM-dd");
      setFilters((f) => ({ ...f, start_date: start, end_date: end }));
    }
  };

  // ---------------------------------------------------------------------------
  // Template click -> drill-down
  // ---------------------------------------------------------------------------

  const handleTemplateClick = async (templateId: string) => {
    setDrillDown({ type: "template", id: templateId });
    try {
      const [funnel, fail] = await Promise.allSettled([
        fetchAnalyticsFunnel(templateId, filters),
        fetchAnalyticsFailures({ ...filters, template_id: templateId }),
      ]);
      if (funnel.status === "fulfilled") setFunnelData(funnel.value);
      if (fail.status === "fulfilled") setFailures(fail.value);
    } catch {
      /* handled by allSettled */
    }
  };

  // ---------------------------------------------------------------------------
  // Lead click -> drill-down
  // ---------------------------------------------------------------------------

  const handleLeadClick = async (leadId: string) => {
    setDrillDown({ type: "lead", id: leadId });
    try {
      const detail = await fetchAnalyticsLeadDetail(leadId);
      setLeadDetail(detail);
    } catch {
      toast.error("Failed to load lead details");
    }
  };

  // ---------------------------------------------------------------------------
  // Sort handler for templates
  // ---------------------------------------------------------------------------

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  };

  const sortedTemplates = [...templates].sort((a, b) => {
    const key = sortCol as keyof TemplateStats;
    const aVal = (a[key] as number) ?? 0;
    const bVal = (b[key] as number) ?? 0;
    return sortDir === "asc" ? aVal - bVal : bVal - aVal;
  });

  const sortIndicator = (col: string) =>
    sortCol === col ? (sortDir === "asc" ? " \u2191" : " \u2193") : "";

  // ---------------------------------------------------------------------------
  // Drill-down view
  // ---------------------------------------------------------------------------

  if (drillDown) {
    return (
      <PageTransition>
        <Header title="Sequence Analytics" />
        <div className="p-6">
          <AnalyticsDrillDown
            type={drillDown.type}
            onBack={() => {
              setDrillDown(null);
              setFunnelData(null);
              setLeadDetail(null);
            }}
            funnelData={funnelData}
            failuresData={failures}
            leadDetail={leadDetail}
          />
        </div>
      </PageTransition>
    );
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <>
      <Header title="Sequence Analytics" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Nav links */}
          <div className="flex items-center gap-1 border-b border-border pb-3">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href}>
                <Button
                  variant={
                    link.href === "/sequences/analytics" ? "secondary" : "ghost"
                  }
                  size="sm"
                >
                  {link.label}
                </Button>
              </Link>
            ))}
          </div>

          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="date"
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={filters.start_date ?? ""}
              onChange={(e) => {
                setActivePreset("");
                setFilters((f) => ({
                  ...f,
                  start_date: e.target.value || undefined,
                }));
              }}
            />
            <span className="text-sm text-muted-foreground">to</span>
            <input
              type="date"
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={filters.end_date ?? ""}
              onChange={(e) => {
                setActivePreset("");
                setFilters((f) => ({
                  ...f,
                  end_date: e.target.value || undefined,
                }));
              }}
            />

            <div className="flex items-center gap-1">
              {DATE_PRESETS.map((p) => (
                <Button
                  key={p.label}
                  variant={activePreset === p.label ? "secondary" : "outline"}
                  size="sm"
                  onClick={() => setPreset(p.days, p.label)}
                >
                  {p.label}
                </Button>
              ))}
            </div>

            <Select
              value={filters.template_id ?? "all"}
              onValueChange={(v) =>
                setFilters((f) => ({
                  ...f,
                  template_id: v === "all" ? undefined : v,
                }))
              }
            >
              <SelectTrigger className="h-9 w-52">
                <SelectValue placeholder="All Templates" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Templates</SelectItem>
                {templateOptions.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={filters.channel ?? "all"}
              onValueChange={(v) =>
                setFilters((f) => ({
                  ...f,
                  channel: v === "all" ? undefined : v,
                }))
              }
            >
              <SelectTrigger className="h-9 w-48">
                <SelectValue placeholder="All Channels" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Channels</SelectItem>
                <SelectItem value="whatsapp_template">
                  WhatsApp Template
                </SelectItem>
                <SelectItem value="whatsapp_session">
                  WhatsApp Session
                </SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
                <SelectItem value="voice_call">Voice Call</SelectItem>
                <SelectItem value="webhook">Webhook</SelectItem>
              </SelectContent>
            </Select>

            <Button
              variant="outline"
              size="sm"
              onClick={loadData}
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

          {/* KPI Cards */}
          {loading ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <KPICard
                label="Total Sent"
                value={overview?.total_sent ?? null}
                trend={overview?.trend?.sent_change ?? null}
                fmt="number"
              />
              <KPICard
                label="Reply Rate"
                value={overview?.reply_rate ?? null}
                trend={overview?.trend?.reply_rate_change ?? null}
                fmt="percent"
              />
              <KPICard
                label="Completion Rate"
                value={overview?.completion_rate ?? null}
                trend={overview?.trend?.completion_rate_change ?? null}
                fmt="percent"
              />
              <KPICard
                label="Avg Reply Time"
                value={overview?.avg_time_to_reply_hours ?? null}
                trend={overview?.trend?.avg_reply_time_change ?? null}
                fmt="hours"
              />
            </div>
          )}

          {/* Charts row: Channel Breakdown + Failure Summary */}
          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Skeleton className="h-48 md:col-span-2" />
              <Skeleton className="h-48" />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Channel Breakdown */}
              <Card className="md:col-span-2">
                <CardContent className="p-4">
                  <p className="text-sm font-medium mb-3">Channel Breakdown</p>
                  {channels.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No channel data available
                    </p>
                  ) : (
                    <div className="space-y-3">
                      {channels.map((ch) => (
                        <div key={ch.channel} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span>
                              {CHANNEL_LABELS[ch.channel] ?? ch.channel}
                            </span>
                            <span className="text-muted-foreground">
                              {ch.sent.toLocaleString()} sent (
                              {(ch.percentage_of_total * 100).toFixed(1)}%)
                            </span>
                          </div>
                          <div className="h-2 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-violet-500 rounded-full transition-all"
                              style={{
                                width: `${Math.max(ch.percentage_of_total * 100, 1)}%`,
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Failure Summary */}
              <Card>
                <CardContent className="p-4">
                  <p className="text-sm font-medium mb-3">Failure Summary</p>
                  {!failures || failures.total_failed === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No failures recorded
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-2xl font-bold text-red-400">
                        {failures.total_failed.toLocaleString()}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        total failed
                      </p>
                      <div className="space-y-2 mt-2">
                        {failures.reasons.slice(0, 3).map((r, i) => (
                          <div
                            key={i}
                            className="flex items-center justify-between text-sm"
                          >
                            <span className="truncate mr-2">{r.reason}</span>
                            <span className="text-muted-foreground shrink-0">
                              {r.count}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {/* Template Performance Table */}
          {loading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="p-4 border-b border-border">
                  <p className="text-sm font-medium flex items-center gap-2">
                    <BarChart3 className="h-4 w-4" />
                    Template Performance
                  </p>
                </div>
                {templates.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                    <p className="text-sm">No template data available</p>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead
                          className="cursor-pointer select-none"
                          onClick={() => handleSort("total_sent")}
                        >
                          Sent{sortIndicator("total_sent")}
                        </TableHead>
                        <TableHead
                          className="cursor-pointer select-none"
                          onClick={() => handleSort("reply_rate")}
                        >
                          Reply %{sortIndicator("reply_rate")}
                        </TableHead>
                        <TableHead
                          className="cursor-pointer select-none"
                          onClick={() => handleSort("completion_rate")}
                        >
                          Completion %{sortIndicator("completion_rate")}
                        </TableHead>
                        <TableHead>Active</TableHead>
                        <TableHead>Funnel</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortedTemplates.map((t) => (
                        <TableRow
                          key={t.template_id}
                          className="cursor-pointer hover:bg-muted/50"
                          onClick={() => handleTemplateClick(t.template_id)}
                        >
                          <TableCell className="font-medium">
                            {t.name}
                          </TableCell>
                          <TableCell>{t.total_sent.toLocaleString()}</TableCell>
                          <TableCell>
                            {(t.reply_rate * 100).toFixed(1)}%
                          </TableCell>
                          <TableCell>
                            {(t.completion_rate * 100).toFixed(1)}%
                          </TableCell>
                          <TableCell>{t.active_instances}</TableCell>
                          <TableCell>
                            <MiniFunnel values={t.funnel_summary} />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          )}

          {/* Lead Engagement Section */}
          {loading ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-20 w-full" />
                ))}
              </div>
              <Skeleton className="h-48 w-full" />
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm font-medium">Lead Engagement</p>

              {/* Tier summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {(
                  [
                    { tier: "hot", label: "Hot", color: "text-green-400" },
                    { tier: "warm", label: "Warm", color: "text-yellow-400" },
                    { tier: "cold", label: "Cold", color: "text-blue-400" },
                    {
                      tier: "inactive",
                      label: "Inactive",
                      color: "text-gray-400",
                    },
                  ] as const
                ).map((item) => (
                  <Card key={item.tier}>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground uppercase tracking-wide">
                        {item.label}
                      </p>
                      <p className={`text-2xl font-bold mt-1 ${item.color}`}>
                        {leads?.tier_summary[item.tier] ?? 0}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>

              {/* Top leads table */}
              <Card>
                <CardContent className="p-0">
                  {!leads || leads.leads.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                      <p className="text-sm">No lead data available</p>
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Name</TableHead>
                          <TableHead>Score</TableHead>
                          <TableHead>Replies</TableHead>
                          <TableHead>Last Interaction</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {leads.leads.map((lead) => (
                          <TableRow
                            key={lead.lead_id}
                            className="cursor-pointer hover:bg-muted/50"
                            onClick={() => handleLeadClick(lead.lead_id)}
                          >
                            <TableCell className="font-medium">
                              {lead.lead_name ?? lead.lead_phone ?? "Unknown"}
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                <span className="tabular-nums">
                                  {lead.score}
                                </span>
                                <TierBadge tier={lead.tier} />
                              </div>
                            </TableCell>
                            <TableCell>{lead.total_replies}</TableCell>
                            <TableCell className="text-muted-foreground">
                              {lead.last_interaction_at
                                ? format(
                                    new Date(lead.last_interaction_at),
                                    "MMM d, yyyy"
                                  )
                                : "\u2014"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
