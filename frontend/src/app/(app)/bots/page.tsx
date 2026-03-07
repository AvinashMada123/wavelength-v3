"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Plus,
  Pencil,
  Trash2,
  Copy,
  Check,
  Bot,
  Volume2,
  Clock,
  Globe,
  Languages,
  MoreVertical,
  Variable,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBots, createBot, updateBot, deleteBot } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { VOICE_GROUPS, LANGUAGE_OPTIONS, BUILTIN_VARIABLES } from "@/lib/constants";
import { Switch } from "@/components/ui/switch";
import type { BotConfig, GHLWorkflow } from "@/types/api";

// ---------- Form types ----------

interface BotForm {
  agent_name: string;
  company_name: string;
  location: string;
  event_name: string;
  event_date: string;
  event_time: string;
  tts_voice: string;
  tts_style_prompt: string;
  language: string;
  system_prompt_template: string;
  context_variables: Record<string, string>;
  silence_timeout_secs: number;
  ghl_webhook_url: string;
  ghl_api_key: string;
  ghl_location_id: string;
  ghl_post_call_tag: string;
  ghl_workflows: GHLWorkflow[];
  max_call_duration: number;
  telephony_provider: "plivo" | "twilio";
  plivo_auth_id: string;
  plivo_auth_token: string;
  plivo_caller_id: string;
  twilio_account_sid: string;
  twilio_auth_token: string;
  twilio_phone_number: string;
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
  language: "en-IN",
  system_prompt_template: "",
  context_variables: {},
  silence_timeout_secs: 5,
  ghl_webhook_url: "",
  ghl_api_key: "",
  ghl_location_id: "",
  ghl_post_call_tag: "",
  ghl_workflows: [],
  max_call_duration: 480,
  telephony_provider: "plivo",
  plivo_auth_id: "",
  plivo_auth_token: "",
  plivo_caller_id: "",
  twilio_account_sid: "",
  twilio_auth_token: "",
  twilio_phone_number: "",
};

const TIMING_OPTIONS = [
  { value: "pre_call", label: "Pre-Call" },
  { value: "during_call", label: "During Call" },
  { value: "post_call", label: "Post-Call" },
] as const;

// Extract {variable_name} from a template string
function extractVariables(template: string): string[] {
  const matches = template.match(/\{(\w+)\}/g);
  if (!matches) return [];
  const names = [...new Set(matches.map((m) => m.slice(1, -1)))];
  return names;
}

// ---------- Page ----------

export default function BotsPage() {
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingBot, setEditingBot] = useState<BotConfig | null>(null);
  const [form, setForm] = useState<BotForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // New custom variable being added
  const [newVarName, setNewVarName] = useState("");

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

  // Variables detected in the current prompt
  const detectedVars = useMemo(
    () => extractVariables(form.system_prompt_template),
    [form.system_prompt_template]
  );

  // Custom variables = detected vars that aren't built-in, plus any in context_variables
  const customVarNames = useMemo(() => {
    const fromPrompt = detectedVars.filter(
      (v) => !BUILTIN_VARIABLES.includes(v)
    );
    const fromSaved = Object.keys(form.context_variables);
    return [...new Set([...fromPrompt, ...fromSaved])];
  }, [detectedVars, form.context_variables]);

  function setContextVar(name: string, value: string) {
    setForm((prev) => ({
      ...prev,
      context_variables: { ...prev.context_variables, [name]: value },
    }));
  }

  function removeContextVar(name: string) {
    setForm((prev) => {
      const next = { ...prev.context_variables };
      delete next[name];
      return { ...prev, context_variables: next };
    });
  }

  function addCustomVariable() {
    const name = newVarName.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    if (!name) return;
    if (BUILTIN_VARIABLES.includes(name)) {
      toast.error(`"${name}" is a built-in variable`);
      return;
    }
    setContextVar(name, "");
    setNewVarName("");
  }

  function addWorkflow() {
    setForm((prev) => ({
      ...prev,
      ghl_workflows: [
        ...prev.ghl_workflows,
        {
          id: crypto.randomUUID(),
          name: "",
          tag: "",
          timing: "post_call" as const,
          enabled: true,
        },
      ],
    }));
  }

  function updateWorkflow(id: string, updates: Partial<GHLWorkflow>) {
    setForm((prev) => ({
      ...prev,
      ghl_workflows: prev.ghl_workflows.map((wf) =>
        wf.id === id ? { ...wf, ...updates } : wf
      ),
    }));
  }

  function removeWorkflow(id: string) {
    setForm((prev) => ({
      ...prev,
      ghl_workflows: prev.ghl_workflows.filter((wf) => wf.id !== id),
    }));
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
      language: bot.language || "en-IN",
      system_prompt_template: bot.system_prompt_template,
      context_variables: bot.context_variables || {},
      silence_timeout_secs: bot.silence_timeout_secs,
      ghl_webhook_url: bot.ghl_webhook_url || "",
      ghl_api_key: bot.ghl_api_key || "",
      ghl_location_id: bot.ghl_location_id || "",
      ghl_post_call_tag: bot.ghl_post_call_tag || "",
      ghl_workflows: bot.ghl_workflows || [],
      max_call_duration: bot.max_call_duration ?? 480,
      telephony_provider: bot.telephony_provider || "plivo",
      plivo_auth_id: "",
      plivo_auth_token: "",
      plivo_caller_id: bot.plivo_caller_id,
      twilio_account_sid: "",
      twilio_auth_token: "",
      twilio_phone_number: bot.twilio_phone_number || "",
    });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.agent_name || !form.company_name || !form.system_prompt_template) {
      toast.error("Agent name, company name, and system prompt are required");
      return;
    }
    if (!editingBot) {
      if (form.telephony_provider === "plivo" && (!form.plivo_auth_id || !form.plivo_auth_token || !form.plivo_caller_id)) {
        toast.error("Plivo credentials are required");
        return;
      }
      if (form.telephony_provider === "twilio" && (!form.twilio_account_sid || !form.twilio_auth_token || !form.twilio_phone_number)) {
        toast.error("Twilio credentials are required");
        return;
      }
    }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(form)) {
        if (k === "context_variables") {
          payload[k] = v;
        } else if (typeof v === "string" && v === "" && k !== "agent_name" && k !== "company_name" && k !== "system_prompt_template") {
          if (!editingBot) payload[k] = null;
        } else {
          payload[k] = v;
        }
      }

      if (editingBot) {
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
    toast.success("Bot ID copied");
    setTimeout(() => setCopiedId(null), 2000);
  }

  const langLabel = (code: string) =>
    LANGUAGE_OPTIONS.find((l) => l.value === code)?.label || code;

  return (
    <>
      <Header title="Bots" />
      <PageTransition>
        <div className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-semibold">Bot Configurations</h2>
              <p className="text-sm text-muted-foreground">
                Manage your voice agents
              </p>
            </div>
            <Button onClick={openCreate}>
              <Plus className="mr-2 h-4 w-4" />
              New Bot
            </Button>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-48" />
              ))}
            </div>
          ) : bots.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Bot className="mb-3 h-12 w-12 text-muted-foreground/30" />
                <p className="text-muted-foreground mb-2">No bots configured yet</p>
                <Button variant="link" onClick={openCreate}>
                  Create your first bot
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {bots.map((bot, i) => (
                <motion.div
                  key={bot.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06 }}
                >
                  <Card className="group relative transition-colors hover:border-violet-500/50">
                    <CardContent className="pt-6">
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 text-white font-bold text-sm">
                            {bot.agent_name.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <h3 className="font-semibold">{bot.agent_name}</h3>
                            <p className="text-sm text-muted-foreground">{bot.company_name}</p>
                          </div>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity">
                              <MoreVertical className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => openEdit(bot)}>
                              <Pencil className="mr-2 h-4 w-4" /> Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => copyId(bot.id)}>
                              {copiedId === bot.id ? <Check className="mr-2 h-4 w-4 text-green-500" /> : <Copy className="mr-2 h-4 w-4" />}
                              Copy ID
                            </DropdownMenuItem>
                            <DropdownMenuItem className="text-destructive" onClick={() => deleteConfirm === bot.id ? handleDelete(bot.id) : setDeleteConfirm(bot.id)}>
                              <Trash2 className="mr-2 h-4 w-4" />
                              {deleteConfirm === bot.id ? "Click to confirm" : "Delete"}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>

                      <div className="flex flex-wrap gap-2 mb-4">
                        <Badge variant={bot.telephony_provider === "twilio" ? "default" : "secondary"} className="gap-1 text-xs">
                          {bot.telephony_provider === "twilio" ? "Twilio" : "Plivo"}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Volume2 className="h-3 w-3" /> {bot.tts_voice}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Languages className="h-3 w-3" /> {langLabel(bot.language)}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Clock className="h-3 w-3" /> {bot.silence_timeout_secs}s
                        </Badge>
                        {bot.location && (
                          <Badge variant="outline" className="gap-1 text-xs">
                            <Globe className="h-3 w-3" /> {bot.location}
                          </Badge>
                        )}
                      </div>

                      <p className="text-xs text-muted-foreground line-clamp-2 mb-4">
                        {bot.system_prompt_template.slice(0, 120)}
                        {bot.system_prompt_template.length > 120 ? "..." : ""}
                      </p>

                      <div className="flex items-center justify-between pt-3 border-t">
                        <Badge variant={bot.is_active ? "default" : "secondary"} className="text-[10px]">
                          {bot.is_active ? "Active" : "Inactive"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">{formatDate(bot.created_at)}</span>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </PageTransition>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{editingBot ? "Edit Bot" : "Create Bot"}</DialogTitle>
          </DialogHeader>
          <ScrollArea className="flex-1 pr-4">
            <div className="space-y-6 pb-4">

              {/* ---- Agent Info ---- */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Agent Info</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="agent_name">Agent Name *</Label>
                    <Input id="agent_name" value={form.agent_name} onChange={(e) => setField("agent_name", e.target.value)} placeholder="Priya" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="company_name">Company Name *</Label>
                    <Input id="company_name" value={form.company_name} onChange={(e) => setField("company_name", e.target.value)} placeholder="Wavelength" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="location">Location</Label>
                    <Input id="location" value={form.location} onChange={(e) => setField("location", e.target.value)} placeholder="Mumbai" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="event_name">Event Name</Label>
                    <Input id="event_name" value={form.event_name} onChange={(e) => setField("event_name", e.target.value)} placeholder="AI Workshop" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="event_date">Event Date</Label>
                    <Input id="event_date" value={form.event_date} onChange={(e) => setField("event_date", e.target.value)} placeholder="2026-03-15" />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="event_time">Event Time</Label>
                  <Input id="event_time" value={form.event_time} onChange={(e) => setField("event_time", e.target.value)} placeholder="10:00 AM" className="w-48" />
                </div>
              </div>

              <Separator />

              {/* ---- Voice & Language ---- */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Voice & Language</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label>Voice</Label>
                    <Select value={form.tts_voice} onValueChange={(v) => setField("tts_voice", v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select voice..." />
                      </SelectTrigger>
                      <SelectContent>
                        {VOICE_GROUPS.map((group) => (
                          <SelectGroup key={group.label}>
                            <SelectLabel>{group.label}</SelectLabel>
                            {group.voices.map((v) => (
                              <SelectItem key={v.value} value={v.value}>
                                {v.label}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Language</Label>
                    <Select value={form.language} onValueChange={(v) => setField("language", v)}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select language..." />
                      </SelectTrigger>
                      <SelectContent>
                        {LANGUAGE_OPTIONS.map((l) => (
                          <SelectItem key={l.value} value={l.value}>
                            {l.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
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
                  <Label htmlFor="tts_style_prompt">Style Prompt</Label>
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
              </div>

              <Separator />

              {/* ---- System Prompt ---- */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">System Prompt</h3>
                <div className="space-y-2">
                  <Label htmlFor="system_prompt_template">Prompt Template *</Label>
                  <Textarea
                    id="system_prompt_template"
                    value={form.system_prompt_template}
                    onChange={(e) => setField("system_prompt_template", e.target.value)}
                    placeholder="You are {agent_name} from {company_name}. You are calling {contact_name}..."
                    className="min-h-[160px] font-mono text-sm"
                  />
                  {detectedVars.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      <span className="text-xs text-muted-foreground mr-1">Variables:</span>
                      {detectedVars.map((v) => (
                        <Badge
                          key={v}
                          variant={BUILTIN_VARIABLES.includes(v) ? "secondary" : "outline"}
                          className="text-[10px] font-mono"
                        >
                          {`{${v}}`}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <Separator />

              {/* ---- Context Variables ---- */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-muted-foreground">Context Variables</h3>
                  <p className="text-xs text-muted-foreground">
                    Set default values for custom {"{variables}"} in your prompt
                  </p>
                </div>

                {/* Built-in variables (read-only info) */}
                {detectedVars.some((v) => BUILTIN_VARIABLES.includes(v)) && (
                  <div className="rounded-lg border p-3 bg-muted/30">
                    <p className="text-xs font-medium text-muted-foreground mb-2">
                      Built-in (auto-filled at call time)
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {detectedVars
                        .filter((v) => BUILTIN_VARIABLES.includes(v))
                        .map((v) => (
                          <Badge key={v} variant="secondary" className="text-xs font-mono gap-1">
                            <Variable className="h-3 w-3" />
                            {v}
                          </Badge>
                        ))}
                    </div>
                  </div>
                )}

                {/* Custom variables with default values */}
                {customVarNames.length > 0 && (
                  <div className="space-y-2">
                    {customVarNames.map((varName) => (
                      <div key={varName} className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs font-mono shrink-0 gap-1">
                          <Variable className="h-3 w-3" />
                          {`{${varName}}`}
                        </Badge>
                        <Input
                          value={form.context_variables[varName] || ""}
                          onChange={(e) => setContextVar(varName, e.target.value)}
                          placeholder="Default value..."
                          className="h-8 text-sm flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0"
                          onClick={() => removeContextVar(varName)}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}

                {/* Add new variable */}
                <div className="flex items-center gap-2">
                  <Input
                    value={newVarName}
                    onChange={(e) => setNewVarName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addCustomVariable()}
                    placeholder="new_variable_name"
                    className="h-8 text-sm font-mono flex-1"
                  />
                  <Button variant="outline" size="sm" onClick={addCustomVariable} disabled={!newVarName.trim()}>
                    <Plus className="h-3.5 w-3.5 mr-1" />
                    Add Variable
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Use {"{variable_name}"} in your prompt. Custom variables can be overridden at call time via <code className="text-[10px] bg-muted px-1 rounded">extra_vars</code> in the API.
                </p>
              </div>

              <Separator />

              {/* ---- Telephony Provider ---- */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-muted-foreground">Telephony Provider</h3>
                  <div className="flex gap-1 rounded-lg border p-0.5">
                    {(["plivo", "twilio"] as const).map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => setField("telephony_provider", p)}
                        className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                          form.telephony_provider === p
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {p === "plivo" ? "Plivo" : "Twilio"}
                      </button>
                    ))}
                  </div>
                </div>

                {form.telephony_provider === "plivo" ? (
                  <>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="plivo_auth_id">Auth ID {!editingBot && "*"}</Label>
                        <Input id="plivo_auth_id" value={form.plivo_auth_id} onChange={(e) => setField("plivo_auth_id", e.target.value)} placeholder={editingBot ? "(unchanged)" : ""} className="font-mono text-sm" />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="plivo_auth_token">Auth Token {!editingBot && "*"}</Label>
                        <Input id="plivo_auth_token" type="password" value={form.plivo_auth_token} onChange={(e) => setField("plivo_auth_token", e.target.value)} placeholder={editingBot ? "(unchanged)" : ""} className="font-mono text-sm" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="plivo_caller_id">Caller ID {!editingBot && "*"}</Label>
                      <Input id="plivo_caller_id" value={form.plivo_caller_id} onChange={(e) => setField("plivo_caller_id", e.target.value)} placeholder="+14155551234" className="font-mono text-sm w-64" />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="twilio_account_sid">Account SID {!editingBot && "*"}</Label>
                        <Input id="twilio_account_sid" value={form.twilio_account_sid} onChange={(e) => setField("twilio_account_sid", e.target.value)} placeholder={editingBot ? "(unchanged)" : ""} className="font-mono text-sm" />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="twilio_auth_token">Auth Token {!editingBot && "*"}</Label>
                        <Input id="twilio_auth_token" type="password" value={form.twilio_auth_token} onChange={(e) => setField("twilio_auth_token", e.target.value)} placeholder={editingBot ? "(unchanged)" : ""} className="font-mono text-sm" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="twilio_phone_number">Phone Number {!editingBot && "*"}</Label>
                      <Input id="twilio_phone_number" value={form.twilio_phone_number} onChange={(e) => setField("twilio_phone_number", e.target.value)} placeholder="+14155551234" className="font-mono text-sm w-64" />
                    </div>
                  </>
                )}
              </div>

              <Separator />

              {/* ---- GHL Credentials ---- */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">GoHighLevel (optional)</h3>
                <div className="space-y-2">
                  <Label htmlFor="ghl_webhook_url">Webhook URL</Label>
                  <Input id="ghl_webhook_url" value={form.ghl_webhook_url} onChange={(e) => setField("ghl_webhook_url", e.target.value)} placeholder="https://services.leadconnectorhq.com/hooks/..." className="font-mono text-sm" />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="ghl_api_key">API Key</Label>
                    <Input id="ghl_api_key" type="password" value={form.ghl_api_key} onChange={(e) => setField("ghl_api_key", e.target.value)} placeholder={editingBot?.ghl_api_key ? "(unchanged)" : ""} className="font-mono text-sm" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ghl_location_id">Location ID</Label>
                    <Input id="ghl_location_id" value={form.ghl_location_id} onChange={(e) => setField("ghl_location_id", e.target.value)} placeholder="e.g. abc123XYZ" className="font-mono text-sm" />
                  </div>
                </div>
              </div>

              <Separator />

              {/* ---- CRM Workflows ---- */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground">CRM Workflow Triggers</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Each workflow adds a tag to the contact in your CRM. Set up CRM automations to trigger on &quot;tag added&quot;.
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={addWorkflow}>
                    <Plus className="h-3.5 w-3.5 mr-1" />
                    Add Workflow
                  </Button>
                </div>

                {form.ghl_workflows.length === 0 && (
                  <div className="rounded-lg border border-dashed p-6 text-center">
                    <p className="text-sm text-muted-foreground">No workflows configured</p>
                  </div>
                )}

                {form.ghl_workflows.map((wf) => (
                  <div key={wf.id} className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 grid grid-cols-2 gap-3">
                        <Input
                          value={wf.name}
                          onChange={(e) => updateWorkflow(wf.id, { name: e.target.value })}
                          placeholder="Workflow Name"
                          className="h-8 text-sm"
                        />
                        <Input
                          value={wf.tag}
                          onChange={(e) => updateWorkflow(wf.id, { tag: e.target.value })}
                          placeholder="CRM Tag"
                          className="h-8 text-sm font-mono"
                        />
                      </div>
                      <Switch
                        checked={wf.enabled}
                        onCheckedChange={(checked) => updateWorkflow(wf.id, { enabled: checked })}
                      />
                      <span className="text-xs text-muted-foreground w-6">{wf.enabled ? "On" : "Off"}</span>
                      <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => removeWorkflow(wf.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>

                    <div className="flex items-center gap-1">
                      <span className="text-xs text-muted-foreground mr-2">Trigger Timing</span>
                      {TIMING_OPTIONS.map((opt) => (
                        <Button
                          key={opt.value}
                          variant={wf.timing === opt.value ? "default" : "outline"}
                          size="sm"
                          className="h-7 text-xs px-3"
                          onClick={() => updateWorkflow(wf.id, { timing: opt.value })}
                        >
                          {opt.label}
                        </Button>
                      ))}
                    </div>

                    {wf.timing === "during_call" && (
                      <div className="space-y-1">
                        <Label className="text-xs">AI Trigger Description</Label>
                        <Textarea
                          value={wf.trigger_description || ""}
                          onChange={(e) => updateWorkflow(wf.id, { trigger_description: e.target.value })}
                          placeholder="e.g. Trigger when the customer confirms they want more information about the course."
                          className="min-h-[60px] text-sm"
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <Separator />

              {/* ---- Additional Options ---- */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground">Additional Options</h3>
                <div className="flex items-center justify-between rounded-lg border p-4">
                  <div>
                    <p className="text-sm font-medium">Max Call Duration</p>
                    <p className="text-xs text-muted-foreground">Maximum duration (in minutes) before the bot wraps up the call</p>
                  </div>
                  <Input
                    type="number"
                    value={Math.round(form.max_call_duration / 60)}
                    onChange={(e) => setField("max_call_duration", (parseInt(e.target.value) || 0) * 60)}
                    min={1}
                    max={60}
                    className="w-20 text-center"
                  />
                </div>
              </div>

            </div>
          </ScrollArea>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving}>{saving ? "Saving..." : "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
