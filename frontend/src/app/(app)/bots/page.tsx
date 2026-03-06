"use client";

import { useEffect, useState, useCallback } from "react";
import { Plus, Pencil, Trash2, Copy, Check } from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fetchBots, createBot, updateBot, deleteBot } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { BotConfig } from "@/types/api";

interface BotForm {
  agent_name: string;
  company_name: string;
  location: string;
  event_name: string;
  event_date: string;
  event_time: string;
  tts_voice: string;
  tts_style_prompt: string;
  system_prompt_template: string;
  silence_timeout_secs: number;
  ghl_webhook_url: string;
  plivo_auth_id: string;
  plivo_auth_token: string;
  plivo_caller_id: string;
}

const EMPTY_FORM: BotForm = {
  agent_name: "",
  company_name: "",
  location: "",
  event_name: "",
  event_date: "",
  event_time: "",
  tts_voice: "Kore",
  tts_style_prompt: "",
  system_prompt_template: "",
  silence_timeout_secs: 5,
  ghl_webhook_url: "",
  plivo_auth_id: "",
  plivo_auth_token: "",
  plivo_caller_id: "",
};

export default function BotsPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingBot, setEditingBot] = useState<BotConfig | null>(null);
  const [form, setForm] = useState<BotForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadBots = useCallback(async () => {
    try {
      const data = await fetchBots();
      setBots(data);
    } catch {
      toast.error("Failed to load bots");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBots();
  }, [loadBots]);

  function setField<K extends keyof BotForm>(key: K, value: BotForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function openCreate() {
    setEditingBot(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEdit(bot: BotConfig) {
    setEditingBot(bot);
    setForm({
      agent_name: bot.agent_name,
      company_name: bot.company_name,
      location: bot.location || "",
      event_name: bot.event_name || "",
      event_date: bot.event_date || "",
      event_time: bot.event_time || "",
      tts_voice: bot.tts_voice,
      tts_style_prompt: bot.tts_style_prompt || "",
      system_prompt_template: bot.system_prompt_template,
      silence_timeout_secs: bot.silence_timeout_secs,
      ghl_webhook_url: bot.ghl_webhook_url || "",
      plivo_auth_id: "",
      plivo_auth_token: "",
      plivo_caller_id: bot.plivo_caller_id,
    });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.agent_name || !form.company_name || !form.system_prompt_template) {
      toast.error("Agent name, company name, and system prompt are required");
      return;
    }
    if (!editingBot && (!form.plivo_auth_id || !form.plivo_auth_token || !form.plivo_caller_id)) {
      toast.error("Plivo credentials are required for new bots");
      return;
    }

    setSaving(true);
    try {
      // Strip empty strings to null for optional fields
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(form)) {
        if (typeof v === "string" && v === "" && k !== "agent_name" && k !== "company_name" && k !== "system_prompt_template") {
          // skip empty optional strings — backend treats absent as no-change for updates
          if (!editingBot) payload[k] = null;
        } else {
          payload[k] = v;
        }
      }

      if (editingBot) {
        // Only send changed fields
        await updateBot(editingBot.id, payload);
        toast.success("Bot updated");
      } else {
        await createBot(payload as never);
        toast.success("Bot created");
      }
      setDialogOpen(false);
      loadBots();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteBot(id);
      toast.success("Bot deleted");
      setDeleteConfirm(null);
      loadBots();
    } catch {
      toast.error("Delete failed");
    }
  }

  function copyId(id: string) {
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <>
      <Header title="Bots" />
      <PageTransition>
        <div className="p-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Bot Configurations</CardTitle>
              <Button onClick={openCreate} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                New Bot
              </Button>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  Loading...
                </div>
              ) : bots.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <p>No bots configured yet.</p>
                  <Button variant="link" onClick={openCreate}>
                    Create your first bot
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Agent</TableHead>
                      <TableHead>Company</TableHead>
                      <TableHead>Voice</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead>ID</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {bots.map((bot) => (
                      <TableRow key={bot.id}>
                        <TableCell className="font-medium">{bot.agent_name}</TableCell>
                        <TableCell>{bot.company_name}</TableCell>
                        <TableCell className="font-mono text-xs">{bot.tts_voice}</TableCell>
                        <TableCell>
                          <Badge variant={bot.is_active ? "default" : "secondary"}>
                            {bot.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(bot.created_at)}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1 font-mono text-xs text-muted-foreground"
                            onClick={() => copyId(bot.id)}
                          >
                            {bot.id.slice(0, 8)}...
                            {copiedId === bot.id ? (
                              <Check className="h-3 w-3 text-green-500" />
                            ) : (
                              <Copy className="h-3 w-3" />
                            )}
                          </Button>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="icon" onClick={() => openEdit(bot)}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            {deleteConfirm === bot.id ? (
                              <Button
                                variant="destructive"
                                size="sm"
                                onClick={() => handleDelete(bot.id)}
                              >
                                Confirm
                              </Button>
                            ) : (
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setDeleteConfirm(bot.id)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
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

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{editingBot ? "Edit Bot" : "Create Bot"}</DialogTitle>
          </DialogHeader>
          <ScrollArea className="flex-1 pr-4">
            <div className="space-y-6 pb-4">
              {/* Agent Info */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Agent Info</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="agent_name">Agent Name *</Label>
                    <Input
                      id="agent_name"
                      value={form.agent_name}
                      onChange={(e) => setField("agent_name", e.target.value)}
                      placeholder="Priya"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="company_name">Company Name *</Label>
                    <Input
                      id="company_name"
                      value={form.company_name}
                      onChange={(e) => setField("company_name", e.target.value)}
                      placeholder="Wavelength"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="location">Location</Label>
                    <Input
                      id="location"
                      value={form.location}
                      onChange={(e) => setField("location", e.target.value)}
                      placeholder="Mumbai"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="event_name">Event Name</Label>
                    <Input
                      id="event_name"
                      value={form.event_name}
                      onChange={(e) => setField("event_name", e.target.value)}
                      placeholder="AI Workshop"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="event_date">Event Date</Label>
                    <Input
                      id="event_date"
                      value={form.event_date}
                      onChange={(e) => setField("event_date", e.target.value)}
                      placeholder="2026-03-15"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="event_time">Event Time</Label>
                  <Input
                    id="event_time"
                    value={form.event_time}
                    onChange={(e) => setField("event_time", e.target.value)}
                    placeholder="10:00 AM"
                    className="w-48"
                  />
                </div>
              </div>

              <Separator />

              {/* Voice & Behavior */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Voice & Behavior</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="tts_voice">TTS Voice</Label>
                    <Input
                      id="tts_voice"
                      value={form.tts_voice}
                      onChange={(e) => setField("tts_voice", e.target.value)}
                      placeholder="Kore"
                      className="font-mono text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="silence_timeout_secs">Silence Timeout (sec)</Label>
                    <Input
                      id="silence_timeout_secs"
                      type="number"
                      value={form.silence_timeout_secs}
                      onChange={(e) => setField("silence_timeout_secs", parseInt(e.target.value) || 0)}
                      min={1}
                      max={30}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tts_style_prompt">TTS Style Prompt</Label>
                  <Textarea
                    id="tts_style_prompt"
                    value={form.tts_style_prompt}
                    onChange={(e) => setField("tts_style_prompt", e.target.value)}
                    placeholder="Speak warmly in Indian English. Natural, calm, conversational tone. Never robotic."
                    className="min-h-[80px] font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    Controls how the TTS voice sounds. Leave empty for default style.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="system_prompt_template">System Prompt Template *</Label>
                  <Textarea
                    id="system_prompt_template"
                    value={form.system_prompt_template}
                    onChange={(e) => setField("system_prompt_template", e.target.value)}
                    placeholder="You are {agent_name} from {company_name}. You are calling {contact_name}..."
                    className="min-h-[160px] font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    Available variables: {"{contact_name}"}, {"{agent_name}"}, {"{company_name}"}, {"{location}"}, {"{event_name}"}, {"{event_date}"}, {"{event_time}"}
                  </p>
                </div>
              </div>

              <Separator />

              {/* Integrations */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Plivo Credentials</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="plivo_auth_id">Auth ID {!editingBot && "*"}</Label>
                    <Input
                      id="plivo_auth_id"
                      value={form.plivo_auth_id}
                      onChange={(e) => setField("plivo_auth_id", e.target.value)}
                      placeholder={editingBot ? "(unchanged)" : ""}
                      className="font-mono text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="plivo_auth_token">Auth Token {!editingBot && "*"}</Label>
                    <Input
                      id="plivo_auth_token"
                      type="password"
                      value={form.plivo_auth_token}
                      onChange={(e) => setField("plivo_auth_token", e.target.value)}
                      placeholder={editingBot ? "(unchanged)" : ""}
                      className="font-mono text-sm"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="plivo_caller_id">Caller ID {!editingBot && "*"}</Label>
                  <Input
                    id="plivo_caller_id"
                    value={form.plivo_caller_id}
                    onChange={(e) => setField("plivo_caller_id", e.target.value)}
                    placeholder="+14155551234"
                    className="font-mono text-sm w-64"
                  />
                </div>
              </div>

              <Separator />

              {/* GHL */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">GoHighLevel (optional)</h3>
                <div className="space-y-2">
                  <Label htmlFor="ghl_webhook_url">Webhook URL</Label>
                  <Input
                    id="ghl_webhook_url"
                    value={form.ghl_webhook_url}
                    onChange={(e) => setField("ghl_webhook_url", e.target.value)}
                    placeholder="https://services.leadconnectorhq.com/hooks/..."
                    className="font-mono text-sm"
                  />
                </div>
              </div>
            </div>
          </ScrollArea>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
