"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
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
  ExternalLink,
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
import { Badge } from "@/components/ui/badge";
import { fetchBots, fetchCallLogs, triggerCall, checkHealth, fetchLeads } from "@/lib/api";
import type { Lead } from "@/lib/api";
import { formatPhoneNumber, timeAgo } from "@/lib/utils";
import { CALL_STATUS_CONFIG } from "@/lib/status-config";
import type { BotConfig, CallLog } from "@/types/api";

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

const RECENT_CALLS_COUNT = 5;

export default function CallsPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [recentCalls, setRecentCalls] = useState<CallLog[]>([]);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  // Trigger form
  const [selectedBotId, setSelectedBotId] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [triggering, setTriggering] = useState(false);

  // Lead search
  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadSearch, setLeadSearch] = useState("");
  const [leadDropdownOpen, setLeadDropdownOpen] = useState(false);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const leadSearchRef = useRef<HTMLInputElement>(null);
  const leadDropdownRef = useRef<HTMLDivElement>(null);

  // Debounced lead search
  useEffect(() => {
    if (!leadSearch.trim()) {
      setLeads([]);
      return;
    }
    const timer = setTimeout(async () => {
      setLoadingLeads(true);
      try {
        const res = await fetchLeads({ search: leadSearch, page_size: 10 });
        setLeads(res.items);
        setLeadDropdownOpen(true);
      } catch {
        setLeads([]);
      } finally {
        setLoadingLeads(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [leadSearch]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (leadDropdownRef.current && !leadDropdownRef.current.contains(e.target as Node)) {
        setLeadDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function selectLead(lead: Lead) {
    setContactName(lead.contact_name);
    setContactPhone(lead.phone_number);
    setLeadSearch("");
    setLeadDropdownOpen(false);
  }

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadRecentCalls = useCallback(async () => {
    try {
      const data = await fetchCallLogs();
      setRecentCalls(data.slice(0, RECENT_CALLS_COUNT));
    } catch {
      // silent polling
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
    checkHealth()
      .then(() => setHealthOk(true))
      .catch(() => setHealthOk(false));
  }, []);

  useEffect(() => {
    setLoading(true);
    loadRecentCalls();
  }, [loadRecentCalls]);

  // Smart polling — fast when calls are active, slow otherwise
  useEffect(() => {
    const hasActive = recentCalls.some((c) =>
      ["initiated", "ringing", "in-progress"].includes(c.status)
    );
    const interval = hasActive ? 3000 : 30000;

    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(loadRecentCalls, interval);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [recentCalls, loadRecentCalls]);

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
      loadRecentCalls();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger call");
    } finally {
      setTriggering(false);
    }
  }

  const activeBots = bots.filter((b) => b.is_active).length;
  const activeCalls = recentCalls.filter((c) =>
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
              { icon: Phone, label: "Total Calls", value: recentCalls.length, gradient: "from-emerald-500 to-green-500" },
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
              <CardDescription>Search for a lead or enter contact details manually</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Lead search */}
              <div className="relative" ref={leadDropdownRef}>
                <Label>Search Leads</Label>
                <div className="relative mt-1.5">
                  <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    ref={leadSearchRef}
                    value={leadSearch}
                    onChange={(e) => setLeadSearch(e.target.value)}
                    onFocus={() => leads.length > 0 && setLeadDropdownOpen(true)}
                    placeholder="Search by name, phone, or email..."
                    className="pl-8"
                  />
                  {loadingLeads && (
                    <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
                  )}
                </div>
                {leadDropdownOpen && leads.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-60 overflow-y-auto">
                    {leads.map((lead) => (
                      <button
                        key={lead.id}
                        type="button"
                        onClick={() => selectLead(lead)}
                        className="flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-accent transition-colors text-left"
                      >
                        <div>
                          <p className="font-medium">{lead.contact_name}</p>
                          <p className="text-xs text-muted-foreground">{lead.phone_number}</p>
                        </div>
                        {lead.company && (
                          <span className="text-xs text-muted-foreground">{lead.company}</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                {leadDropdownOpen && leadSearch.trim() && !loadingLeads && leads.length === 0 && (
                  <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg px-3 py-4 text-center text-sm text-muted-foreground">
                    No leads found
                  </div>
                )}
              </div>

              {/* Bot + Contact fields */}
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

          {/* Recent calls — compact mini-list */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base">Recent Calls</CardTitle>
                  <CardDescription>Last {RECENT_CALLS_COUNT} triggered calls</CardDescription>
                </div>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/call-logs" className="gap-1.5">
                    View All
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="h-10 w-full animate-pulse rounded bg-muted" />
                  ))}
                </div>
              ) : recentCalls.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <Phone className="mb-2 h-8 w-8 opacity-30" />
                  <p className="text-sm">No calls yet</p>
                </div>
              ) : (
                <div className="divide-y">
                  {recentCalls.map((call) => (
                    <Link
                      key={call.id}
                      href={`/calls/${call.id}`}
                      className="flex items-center justify-between py-2.5 px-1 hover:bg-accent/50 rounded transition-colors -mx-1"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <StatusBadge status={call.status} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{call.contact_name}</p>
                          <p className="text-xs text-muted-foreground">{formatPhoneNumber(call.contact_phone)}</p>
                        </div>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap ml-3">
                        {timeAgo(call.created_at)}
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
