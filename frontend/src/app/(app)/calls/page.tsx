"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Phone,
  PhoneCall,
  Bot,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Badge } from "@/components/ui/badge";
import { fetchBots, fetchCallLogs, triggerCall, checkHealth } from "@/lib/api";
import { formatDate, formatDuration, formatPhoneNumber } from "@/lib/utils";
import type { BotConfig, CallLog } from "@/types/api";

const STATUS_STYLES: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; icon: typeof Clock }> = {
  initiated: { variant: "outline", icon: Clock },
  ringing: { variant: "outline", icon: PhoneCall },
  "in-progress": { variant: "default", icon: Activity },
  completed: { variant: "secondary", icon: CheckCircle2 },
  failed: { variant: "destructive", icon: XCircle },
  "no-answer": { variant: "secondary", icon: Phone },
  busy: { variant: "secondary", icon: Phone },
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || { variant: "outline" as const, icon: Clock };
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} className="gap-1">
      <Icon className="h-3 w-3" />
      {status}
    </Badge>
  );
}

export default function CallsPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [selectedBotId, setSelectedBotId] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [triggering, setTriggering] = useState(false);
  const [filterBotId, setFilterBotId] = useState<string>("all");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadCalls = useCallback(async () => {
    try {
      const data = await fetchCallLogs(filterBotId && filterBotId !== "all" ? filterBotId : undefined);
      setCalls(data);
    } catch {
      // silent — polling
    }
  }, [filterBotId]);

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
    checkHealth().then(() => setHealthOk(true)).catch(() => setHealthOk(false));
  }, []);

  useEffect(() => {
    loadCalls();
  }, [loadCalls]);

  // Smart polling: 3s if active calls, 30s otherwise
  useEffect(() => {
    function getPollInterval() {
      const hasActive = calls.some((c) =>
        ["initiated", "ringing", "in-progress"].includes(c.status)
      );
      return hasActive ? 3000 : 30000;
    }

    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(loadCalls, getPollInterval());

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [calls, loadCalls]);

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
      toast.success(`Call triggered: ${res.call_sid.slice(0, 8)}...`);
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
  const totalCalls = calls.length;

  return (
    <>
      <Header title="Calls" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Stats bar */}
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="flex items-center gap-3 pt-6">
                <Bot className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{activeBots}</p>
                  <p className="text-sm text-muted-foreground">Active Bots</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-center gap-3 pt-6">
                <Phone className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{totalCalls}</p>
                  <p className="text-sm text-muted-foreground">Total Calls</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-center gap-3 pt-6">
                <Activity className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">
                    {healthOk === null ? "..." : healthOk ? "OK" : "Down"}
                  </p>
                  <p className="text-sm text-muted-foreground">API Health</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trigger call form */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Trigger Call</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-4">
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

          {/* Call logs */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Call History</CardTitle>
              <Select value={filterBotId} onValueChange={setFilterBotId}>
                <SelectTrigger className="w-48">
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
            </CardHeader>
            <CardContent>
              {calls.length === 0 ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  No calls yet.
                </div>
              ) : (
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
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {calls.map((call) => (
                      <TableRow key={call.id}>
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
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(call.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
