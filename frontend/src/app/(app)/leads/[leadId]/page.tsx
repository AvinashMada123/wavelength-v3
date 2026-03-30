"use client";

import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  User,
  Phone,
  Mail,
  Building2,
  MapPin,
  Clock,
  CalendarDays,
  MessageSquare,
  TrendingUp,
  XCircle,
  Hash,
  Tag,
  ExternalLink,
  ShieldAlert,
  ShieldOff,
} from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLead, useLeadCalls } from "@/hooks/use-leads";
import { addDnc, removeDnc } from "@/lib/api";
import { formatDuration, formatDate } from "@/lib/utils";
import type { CallLog } from "@/types/api";
import { SequencesTab } from "@/app/(app)/leads/components/SequencesTab";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const STATUS_COLORS: Record<string, string> = {
  new: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  contacted: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  qualified: "bg-green-500/15 text-green-400 border-green-500/25",
  unqualified: "bg-red-500/15 text-red-400 border-red-500/25",
};

const QUALIFICATION_COLORS: Record<string, string> = {
  hot: "bg-red-500/15 text-red-400 border-red-500/25",
  warm: "bg-orange-500/15 text-orange-400 border-orange-500/25",
  cold: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  high: "bg-green-500/15 text-green-400 border-green-500/25",
  medium: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  low: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
};

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof User;
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium truncate">
          {value || <span className="text-muted-foreground">--</span>}
        </p>
      </div>
    </div>
  );
}

function CallTimelineEntry({
  call,
  onClick,
}: {
  call: CallLog;
  onClick: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className="relative pl-6 pb-6 last:pb-0"
    >
      {/* Timeline line */}
      <div className="absolute left-[7px] top-3 bottom-0 w-px bg-border last:hidden" />
      {/* Timeline dot */}
      <div className="absolute left-0 top-2 h-4 w-4 rounded-full border-2 border-violet-500 bg-background" />

      <button
        onClick={onClick}
        className="w-full text-left rounded-lg border p-4 hover:border-violet-500/30 hover:bg-muted/30 transition-colors cursor-pointer"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <CalendarDays className="h-3.5 w-3.5" />
            {call.started_at
              ? format(new Date(call.started_at), "MMM d, yyyy h:mm a")
              : format(new Date(call.created_at), "MMM d, yyyy h:mm a")}
          </div>
          <div className="flex items-center gap-2">
            {call.call_duration !== null && call.call_duration !== undefined && (
              <span className="text-xs text-muted-foreground">
                {formatDuration(call.call_duration)}
              </span>
            )}
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className={
              call.status === "completed"
                ? "bg-green-500/15 text-green-400 border-green-500/25"
                : call.status === "failed"
                ? "bg-red-500/15 text-red-400 border-red-500/25"
                : "bg-zinc-500/15 text-zinc-400 border-zinc-500/25"
            }
          >
            {call.status}
          </Badge>
          {call.outcome && (
            <Badge variant="outline" className="bg-violet-500/10 text-violet-400 border-violet-500/25">
              {call.outcome}
            </Badge>
          )}
          {call.analytics?.goal_outcome && (
            <Badge variant="outline" className="bg-indigo-500/10 text-indigo-400 border-indigo-500/25">
              {call.analytics.goal_outcome}
            </Badge>
          )}
        </div>

        {call.summary && (
          <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
            {call.summary}
          </p>
        )}
      </button>
    </motion.div>
  );
}

export default function LeadDetailPage() {
  const params = useParams();
  const router = useRouter();
  const leadId = params.leadId as string;

  const { data: lead, isLoading, error } = useLead(leadId);
  const queryClient = useQueryClient();
  const [dncLoading, setDncLoading] = useState(false);
  const [showDncConfirm, setShowDncConfirm] = useState<"add" | "remove" | null>(null);
  const [dncReason, setDncReason] = useState("");

  // Fetch calls for this lead via dedicated API endpoint
  const { data: leadCalls = [], isLoading: callsLoading } = useLeadCalls(leadId);

  const handleDncToggle = async () => {
    if (!lead) return;
    setDncLoading(true);
    try {
      if (lead.dnc_blocked) {
        await removeDnc(lead.phone_number);
      } else {
        await addDnc(lead.phone_number, dncReason || "Manually blocked via UI");
      }
      queryClient.invalidateQueries({ queryKey: ["lead", leadId] });
    } catch (err) {
      console.error("DNC toggle failed:", err);
    } finally {
      setDncLoading(false);
      setShowDncConfirm(null);
      setDncReason("");
    }
  };

  if (isLoading) {
    return (
      <>
        <Header title="Lead Details" />
        <PageTransition>
          <div className="space-y-6 p-6">
            <Skeleton className="h-8 w-48" />
            <div className="grid gap-6 lg:grid-cols-3">
              <Skeleton className="h-80" />
              <Skeleton className="h-80 lg:col-span-2" />
            </div>
          </div>
        </PageTransition>
      </>
    );
  }

  if (error || !lead) {
    return (
      <>
        <Header title="Lead Details" />
        <PageTransition>
          <div className="space-y-6 p-6">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/leads")}
              className="gap-1"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Leads
            </Button>
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <XCircle className="h-10 w-10 text-red-400 mb-3" />
                <p className="text-sm text-muted-foreground">
                  {error?.message || "Lead not found"}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => router.push("/leads")}
                >
                  Back to Leads
                </Button>
              </CardContent>
            </Card>
          </div>
        </PageTransition>
      </>
    );
  }

  // Aggregate insights
  const totalCalls = lead.call_count || leadCalls.length;
  const lastCallDate = lead.last_call_date;
  const completedCalls = leadCalls.filter((c) => c.status === "completed");
  const avgDuration =
    completedCalls.length > 0
      ? completedCalls.reduce((sum, c) => sum + (c.call_duration || 0), 0) /
        completedCalls.length
      : null;

  return (
    <>
      <Header title="Lead Details" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Back button + Header */}
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/leads")}
              className="gap-1"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold tracking-tight">
                {lead.contact_name}
              </h1>
              <Badge
                variant="outline"
                className={
                  STATUS_COLORS[lead.status] || "text-muted-foreground"
                }
              >
                {lead.status}
              </Badge>
              {lead.dnc_blocked && (
                <Badge variant="outline" className="bg-red-500/15 text-red-400 border-red-500/25">
                  DNC
                </Badge>
              )}
              {lead.qualification_level && (
                <Badge
                  variant="outline"
                  className={
                    QUALIFICATION_COLORS[lead.qualification_level.toLowerCase()] ||
                    "text-muted-foreground"
                  }
                >
                  {lead.qualification_level}
                  {lead.qualification_confidence !== null &&
                    lead.qualification_confidence !== undefined &&
                    ` (${Math.round(lead.qualification_confidence * 100)}%)`}
                </Badge>
              )}
            </div>
          </div>

          {/* DNC Banner */}
          {lead.dnc_blocked && (
            <div className="flex items-center justify-between rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
              <div className="flex items-center gap-3">
                <ShieldAlert className="h-5 w-5 text-red-400" />
                <div>
                  <p className="text-sm font-medium text-red-400">Do Not Call</p>
                  <p className="text-xs text-red-400/70">
                    {lead.dnc_reason || "This contact is on the Do Not Call list"}
                  </p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="border-red-500/30 text-red-400 hover:bg-red-500/10"
                onClick={() => setShowDncConfirm("remove")}
                disabled={dncLoading}
              >
                <ShieldOff className="mr-1 h-3.5 w-3.5" />
                Remove from DNC
              </Button>
            </div>
          )}

          {/* DNC Add/Remove Confirmation Dialog */}
          <Dialog open={showDncConfirm !== null} onOpenChange={() => setShowDncConfirm(null)}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {showDncConfirm === "remove"
                    ? "Remove from Do Not Call list?"
                    : "Add to Do Not Call list?"}
                </DialogTitle>
                <DialogDescription>
                  {showDncConfirm === "remove" ? (
                    <>
                      This contact previously said: &ldquo;{lead.dnc_reason || "Do not call"}&rdquo;.
                      Removing will allow future calls and prevent automatic re-addition.
                    </>
                  ) : (
                    <>
                      This will block all future calls to {lead.contact_name} across all bots and campaigns.
                      <input
                        type="text"
                        placeholder="Reason (optional)"
                        value={dncReason}
                        onChange={(e) => setDncReason(e.target.value)}
                        className="mt-3 w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500"
                      />
                    </>
                  )}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setShowDncConfirm(null)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleDncToggle}
                  className="bg-red-600 hover:bg-red-700 text-white"
                  disabled={dncLoading}
                >
                  {dncLoading ? "Processing..." : showDncConfirm === "remove" ? "Remove" : "Block"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Tabs defaultValue="overview" className="space-y-4">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="calls">Call History</TabsTrigger>
              <TabsTrigger value="sequences">Sequences</TabsTrigger>
            </TabsList>

            {/* Overview tab */}
            <TabsContent value="overview">
              <div className="grid gap-6 lg:grid-cols-3">
                {/* Profile Card */}
                <div className="space-y-6">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Profile</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-1">
                      <InfoRow icon={User} label="Name" value={lead.contact_name} />
                      <Separator />
                      <InfoRow icon={Phone} label="Phone" value={lead.phone_number} />
                      <Separator />
                      <InfoRow icon={Mail} label="Email" value={lead.email} />
                      <Separator />
                      <InfoRow icon={Building2} label="Company" value={lead.company} />
                      <Separator />
                      <InfoRow icon={MapPin} label="Location" value={lead.location} />
                      <Separator />
                      <InfoRow icon={Tag} label="Source" value={lead.source} />
                      <Separator />
                      <InfoRow
                        icon={CalendarDays}
                        label="Created"
                        value={format(new Date(lead.created_at), "MMM d, yyyy")}
                      />
                    </CardContent>
                  </Card>

                  {/* DNC Action */}
                  {!lead.dnc_blocked && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full border-red-500/30 text-red-400 hover:bg-red-500/10"
                      onClick={() => setShowDncConfirm("add")}
                      disabled={dncLoading}
                    >
                      <ShieldAlert className="mr-1.5 h-3.5 w-3.5" />
                      Add to Do Not Call List
                    </Button>
                  )}

                  {/* Aggregated Insights */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Insights</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-xs text-muted-foreground">
                            Total Calls
                          </p>
                          <p className="text-lg font-semibold">{totalCalls}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">
                            Last Call
                          </p>
                          <p className="text-sm font-medium">
                            {lastCallDate
                              ? format(new Date(lastCallDate), "MMM d, yyyy")
                              : "--"}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">
                            Avg Duration
                          </p>
                          <p className="text-sm font-medium">
                            {avgDuration !== null
                              ? formatDuration(avgDuration)
                              : "--"}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">
                            Qualification
                          </p>
                          <p className="text-sm font-medium capitalize">
                            {lead.qualification_level || "--"}
                          </p>
                        </div>
                      </div>
                      {lead.bot_notes && (
                        <div className="mt-4">
                          <p className="text-xs text-muted-foreground mb-1">
                            Bot Notes
                          </p>
                          <p className="text-sm text-foreground/80 whitespace-pre-line rounded-md bg-muted/50 p-3">
                            {lead.bot_notes}
                          </p>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>

                {/* Call History Preview */}
                <div className="lg:col-span-2">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Recent Calls</CardTitle>
                      <CardDescription>
                        Latest calls — switch to Call History tab for full list
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      {callsLoading ? (
                        <div className="space-y-4">
                          {Array.from({ length: 3 }).map((_, i) => (
                            <Skeleton key={i} className="h-24 w-full" />
                          ))}
                        </div>
                      ) : leadCalls.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                          <Phone className="h-10 w-10 opacity-30 mb-3" />
                          <p className="text-sm font-medium">No calls yet</p>
                          <p className="text-xs mt-1">
                            Calls to this lead will appear here
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-0">
                          {leadCalls.slice(0, 3).map((call, i) => (
                            <motion.div
                              key={call.id}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ delay: i * 0.05 }}
                            >
                              <CallTimelineEntry
                                call={call}
                                onClick={() => router.push(`/calls/${call.id}`)}
                              />
                            </motion.div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </div>
            </TabsContent>

            {/* Call History tab */}
            <TabsContent value="calls">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Call History</CardTitle>
                  <CardDescription>
                    All calls made to this lead, newest first
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {callsLoading ? (
                    <div className="space-y-4">
                      {Array.from({ length: 3 }).map((_, i) => (
                        <Skeleton key={i} className="h-24 w-full" />
                      ))}
                    </div>
                  ) : leadCalls.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                      <Phone className="h-10 w-10 opacity-30 mb-3" />
                      <p className="text-sm font-medium">No calls yet</p>
                      <p className="text-xs mt-1">
                        Calls to this lead will appear here
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-0">
                      {leadCalls.map((call, i) => (
                        <motion.div
                          key={call.id}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: i * 0.05 }}
                        >
                          <CallTimelineEntry
                            call={call}
                            onClick={() => router.push(`/calls/${call.id}`)}
                          />
                        </motion.div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Sequences tab */}
            <TabsContent value="sequences">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Engagement Sequences</CardTitle>
                  <CardDescription>
                    Active and past sequences running for this lead
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <SequencesTab leadId={leadId} />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </PageTransition>
    </>
  );
}
