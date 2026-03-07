"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  Plus,
  Trash2,
  Variable,
  X,
  Save,
  Loader2,
  User,
  Mic,
  Phone,
  Link2,
  Settings,
  Info,
  Copy,
  Check,
  Webhook,
} from "lucide-react";
import { toast } from "sonner";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { fetchBot, createBot, updateBot } from "@/lib/api";
import { GEMINI_VOICE_GROUPS, SARVAM_VOICE_GROUPS, LANGUAGE_OPTIONS, BUILTIN_VARIABLES, TTS_PROVIDER_OPTIONS } from "@/lib/constants";
import type { BotConfig, GHLWorkflow } from "@/types/api";

// ---------------------------------------------------------------------------
// Form type
// ---------------------------------------------------------------------------

interface BotForm {
  agent_name: string;
  company_name: string;
  location: string;
  event_name: string;
  event_date: string;
  event_time: string;
  tts_provider: "gemini" | "sarvam";
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
  tts_provider: "gemini",
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractVariables(template: string): string[] {
  const matches = template.match(/\{(\w+)\}/g);
  if (!matches) return [];
  return [...new Set(matches.map((m) => m.slice(1, -1)))];
}

function botToForm(bot: BotConfig): BotForm {
  return {
    agent_name: bot.agent_name,
    company_name: bot.company_name,
    location: bot.location || "",
    event_name: bot.event_name || "",
    event_date: bot.event_date || "",
    event_time: bot.event_time || "",
    tts_provider: bot.tts_provider || "gemini",
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
  };
}

// ---------------------------------------------------------------------------
// Section wrapper for consistent spacing inside tabs
// ---------------------------------------------------------------------------

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {description && (
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BotEditorPage() {
  const router = useRouter();
  const params = useParams();
  const botId = params.botId as string;
  const isNew = botId === "new";

  const [form, setForm] = useState<BotForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [copiedCurl, setCopiedCurl] = useState(false);
  const [newVarName, setNewVarName] = useState("");

  // ---- Data loading ----

  const loadBot = useCallback(async () => {
    try {
      const bot = await fetchBot(botId);
      setForm(botToForm(bot));
    } catch {
      toast.error("Failed to load bot configuration");
      router.push("/bots");
    } finally {
      setLoading(false);
    }
  }, [botId, router]);

  useEffect(() => {
    if (!isNew) {
      loadBot();
    }
  }, [isNew, loadBot]);

  // ---- Form helpers ----

  function setField<K extends keyof BotForm>(key: K, value: BotForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // ---- Variable extraction ----

  const detectedVars = useMemo(
    () => extractVariables(form.system_prompt_template),
    [form.system_prompt_template],
  );

  const customVarNames = useMemo(() => {
    const fromPrompt = detectedVars.filter(
      (v) => !BUILTIN_VARIABLES.includes(v),
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
    const name = newVarName
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_")
      .replace(/[^a-z0-9_]/g, "");
    if (!name) return;
    if (BUILTIN_VARIABLES.includes(name)) {
      toast.error(`"${name}" is a built-in variable`);
      return;
    }
    setContextVar(name, "");
    setNewVarName("");
  }

  // ---- Workflow helpers ----

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
        wf.id === id ? { ...wf, ...updates } : wf,
      ),
    }));
  }

  function removeWorkflow(id: string) {
    setForm((prev) => ({
      ...prev,
      ghl_workflows: prev.ghl_workflows.filter((wf) => wf.id !== id),
    }));
  }

  // ---- Validation & save ----

  async function handleSave() {
    if (
      !form.agent_name ||
      !form.company_name ||
      !form.system_prompt_template
    ) {
      toast.error(
        "Agent name, company name, and system prompt are required",
      );
      return;
    }

    if (isNew) {
      if (
        form.telephony_provider === "plivo" &&
        (!form.plivo_auth_id ||
          !form.plivo_auth_token ||
          !form.plivo_caller_id)
      ) {
        toast.error("Plivo credentials are required for new bots");
        return;
      }
      if (
        form.telephony_provider === "twilio" &&
        (!form.twilio_account_sid ||
          !form.twilio_auth_token ||
          !form.twilio_phone_number)
      ) {
        toast.error("Twilio credentials are required for new bots");
        return;
      }
    }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(form)) {
        if (k === "context_variables" || k === "ghl_workflows") {
          payload[k] = v;
        } else if (
          typeof v === "string" &&
          v === "" &&
          k !== "agent_name" &&
          k !== "company_name" &&
          k !== "system_prompt_template"
        ) {
          if (isNew) payload[k] = null;
          // On edit, omit empty strings for secret fields so backend keeps existing values
        } else {
          payload[k] = v;
        }
      }

      if (isNew) {
        await createBot(payload as never);
        toast.success("Bot created successfully");
      } else {
        await updateBot(botId, payload);
        toast.success("Bot updated successfully");
      }
      router.push("/bots");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save bot");
    } finally {
      setSaving(false);
    }
  }

  // ---- Loading skeleton ----

  if (loading) {
    return (
      <>
        <Header title="Loading..." />
        <PageTransition>
          <div className="p-6 max-w-4xl mx-auto space-y-6">
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-9 rounded-lg" />
              <Skeleton className="h-7 w-48" />
            </div>
            <Skeleton className="h-10 w-full max-w-md" />
            <div className="space-y-4 mt-6">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          </div>
        </PageTransition>
      </>
    );
  }

  // ---- Render ----

  return (
    <>
      <Header title={isNew ? "Create Bot" : "Edit Bot"} />
      <PageTransition>
        <div className="flex flex-col h-[calc(100vh-3.5rem)]">
          {/* Top bar with back button and save */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                onClick={() => router.push("/bots")}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <div>
                <h2 className="text-lg font-semibold">
                  {isNew ? "Create New Bot" : `Edit: ${form.agent_name || "Bot"}`}
                </h2>
                <p className="text-xs text-muted-foreground">
                  {isNew
                    ? "Configure a new voice agent"
                    : `ID: ${botId}`}
                </p>
              </div>
            </div>
            <Button onClick={handleSave} disabled={saving} className="min-w-[100px]">
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="mr-2 h-4 w-4" />
                  Save
                </>
              )}
            </Button>
          </div>

          {/* Tabs area */}
          <ScrollArea className="flex-1">
            <div className="max-w-4xl mx-auto px-6 py-6">
              <Tabs defaultValue="general" className="w-full">
                <TabsList className="w-full justify-start mb-6">
                  <TabsTrigger value="general" className="gap-1.5">
                    <User className="h-3.5 w-3.5" />
                    General
                  </TabsTrigger>
                  <TabsTrigger value="voice-prompt" className="gap-1.5">
                    <Mic className="h-3.5 w-3.5" />
                    Voice & Prompt
                  </TabsTrigger>
                  <TabsTrigger value="telephony" className="gap-1.5">
                    <Phone className="h-3.5 w-3.5" />
                    Telephony
                  </TabsTrigger>
                  <TabsTrigger value="integrations" className="gap-1.5">
                    <Link2 className="h-3.5 w-3.5" />
                    Integrations
                  </TabsTrigger>
                  <TabsTrigger value="settings" className="gap-1.5">
                    <Settings className="h-3.5 w-3.5" />
                    Settings
                  </TabsTrigger>
                </TabsList>

                {/* ================================================================
                    TAB 1: General
                   ================================================================ */}
                <TabsContent value="general">
                  <Card>
                    <CardContent className="pt-6 space-y-8">
                      <Section
                        title="Agent Identity"
                        description="Basic information about your voice agent."
                      >
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label htmlFor="agent_name">
                              Agent Name <span className="text-destructive">*</span>
                            </Label>
                            <Input
                              id="agent_name"
                              value={form.agent_name}
                              onChange={(e) =>
                                setField("agent_name", e.target.value)
                              }
                              placeholder="Priya"
                            />
                            <p className="text-xs text-muted-foreground">
                              The name your bot introduces itself as.
                            </p>
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="company_name">
                              Company Name <span className="text-destructive">*</span>
                            </Label>
                            <Input
                              id="company_name"
                              value={form.company_name}
                              onChange={(e) =>
                                setField("company_name", e.target.value)
                              }
                              placeholder="Wavelength"
                            />
                            <p className="text-xs text-muted-foreground">
                              The organization the agent represents.
                            </p>
                          </div>
                        </div>
                      </Section>

                      <Separator />

                      <Section
                        title="Location & Event"
                        description="Optional context for location-based or event-driven calls."
                      >
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label htmlFor="location">Location</Label>
                            <Input
                              id="location"
                              value={form.location}
                              onChange={(e) =>
                                setField("location", e.target.value)
                              }
                              placeholder="Mumbai"
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="event_name">Event Name</Label>
                            <Input
                              id="event_name"
                              value={form.event_name}
                              onChange={(e) =>
                                setField("event_name", e.target.value)
                              }
                              placeholder="AI Workshop"
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="event_date">Event Date</Label>
                            <Input
                              id="event_date"
                              value={form.event_date}
                              onChange={(e) =>
                                setField("event_date", e.target.value)
                              }
                              placeholder="2026-03-15"
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="event_time">Event Time</Label>
                            <Input
                              id="event_time"
                              value={form.event_time}
                              onChange={(e) =>
                                setField("event_time", e.target.value)
                              }
                              placeholder="10:00 AM"
                            />
                          </div>
                        </div>
                      </Section>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* ================================================================
                    TAB 2: Voice & Prompt
                   ================================================================ */}
                <TabsContent value="voice-prompt">
                  <div className="space-y-6">
                    {/* Voice & Language card */}
                    <Card>
                      <CardContent className="pt-6 space-y-8">
                        <Section
                          title="Voice & Language"
                          description="Choose the TTS provider, voice personality, and language for your agent."
                        >
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            <div className="space-y-2">
                              <Label>TTS Provider</Label>
                              <Select
                                value={form.tts_provider}
                                onValueChange={(v) => {
                                  setField("tts_provider", v as "gemini" | "sarvam");
                                  // Reset voice to provider default
                                  setField("tts_voice", v === "sarvam" ? "priya" : "Kore");
                                }}
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="Select provider..." />
                                </SelectTrigger>
                                <SelectContent>
                                  {TTS_PROVIDER_OPTIONS.map((p) => (
                                    <SelectItem key={p.value} value={p.value}>
                                      {p.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-2">
                              <Label>Voice</Label>
                              <Select
                                value={form.tts_voice}
                                onValueChange={(v) =>
                                  setField("tts_voice", v)
                                }
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="Select voice..." />
                                </SelectTrigger>
                                <SelectContent>
                                  {(form.tts_provider === "sarvam" ? SARVAM_VOICE_GROUPS : GEMINI_VOICE_GROUPS).map((group) => (
                                    <SelectGroup key={group.label}>
                                      <SelectLabel>{group.label}</SelectLabel>
                                      {group.voices.map((v) => (
                                        <SelectItem
                                          key={v.value}
                                          value={v.value}
                                        >
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
                              <Select
                                value={form.language}
                                onValueChange={(v) =>
                                  setField("language", v)
                                }
                              >
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
                          </div>
                        </Section>

                        <Separator />

                        <Section
                          title="Style Prompt"
                          description="Controls how the TTS voice sounds. Leave empty for default style."
                        >
                          <Textarea
                            id="tts_style_prompt"
                            value={form.tts_style_prompt}
                            onChange={(e) =>
                              setField("tts_style_prompt", e.target.value)
                            }
                            placeholder="Speak warmly in Indian English. Natural, calm, conversational tone. Never robotic."
                            className="min-h-[80px] font-mono text-sm"
                          />
                        </Section>
                      </CardContent>
                    </Card>

                    {/* System Prompt card */}
                    <Card>
                      <CardContent className="pt-6 space-y-8">
                        <Section
                          title="System Prompt"
                          description="The main instruction template for your voice agent. Use {variable_name} placeholders."
                        >
                          <div className="space-y-3">
                            <Label htmlFor="system_prompt_template">
                              Prompt Template{" "}
                              <span className="text-destructive">*</span>
                            </Label>
                            <Textarea
                              id="system_prompt_template"
                              value={form.system_prompt_template}
                              onChange={(e) =>
                                setField(
                                  "system_prompt_template",
                                  e.target.value,
                                )
                              }
                              placeholder="You are {agent_name} from {company_name}. You are calling {contact_name}..."
                              className="min-h-[200px] font-mono text-sm"
                            />
                            {detectedVars.length > 0 && (
                              <div className="flex flex-wrap gap-1.5">
                                <span className="text-xs text-muted-foreground mr-1 self-center">
                                  Detected variables:
                                </span>
                                {detectedVars.map((v) => (
                                  <Badge
                                    key={v}
                                    variant={
                                      BUILTIN_VARIABLES.includes(v)
                                        ? "secondary"
                                        : "outline"
                                    }
                                    className="text-[10px] font-mono"
                                  >
                                    {`{${v}}`}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                        </Section>

                        <Separator />

                        {/* Context Variables */}
                        <Section
                          title="Context Variables"
                          description="Set default values for custom {variables} in your prompt. Built-in variables are auto-filled at call time."
                        >
                          {/* Built-in variables (read-only info) */}
                          {detectedVars.some((v) =>
                            BUILTIN_VARIABLES.includes(v),
                          ) && (
                            <div className="rounded-lg border p-3 bg-muted/30">
                              <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
                                <Info className="h-3 w-3" />
                                Built-in (auto-filled at call time)
                              </p>
                              <div className="flex flex-wrap gap-2">
                                {detectedVars
                                  .filter((v) =>
                                    BUILTIN_VARIABLES.includes(v),
                                  )
                                  .map((v) => (
                                    <Badge
                                      key={v}
                                      variant="secondary"
                                      className="text-xs font-mono gap-1"
                                    >
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
                                <div
                                  key={varName}
                                  className="flex items-center gap-2"
                                >
                                  <Badge
                                    variant="outline"
                                    className="text-xs font-mono shrink-0 gap-1"
                                  >
                                    <Variable className="h-3 w-3" />
                                    {`{${varName}}`}
                                  </Badge>
                                  <Input
                                    value={
                                      form.context_variables[varName] || ""
                                    }
                                    onChange={(e) =>
                                      setContextVar(varName, e.target.value)
                                    }
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
                              onKeyDown={(e) =>
                                e.key === "Enter" && addCustomVariable()
                              }
                              placeholder="new_variable_name"
                              className="h-8 text-sm font-mono flex-1"
                            />
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={addCustomVariable}
                              disabled={!newVarName.trim()}
                            >
                              <Plus className="h-3.5 w-3.5 mr-1" />
                              Add Variable
                            </Button>
                          </div>
                          <p className="text-xs text-muted-foreground">
                            Use {"{variable_name}"} in your prompt. Custom
                            variables can be overridden per-call via{" "}
                            <code className="text-[10px] bg-muted px-1 rounded">
                              extra_vars
                            </code>{" "}
                            in the API.
                          </p>
                        </Section>
                      </CardContent>
                    </Card>
                  </div>
                </TabsContent>

                {/* ================================================================
                    TAB 3: Telephony
                   ================================================================ */}
                <TabsContent value="telephony">
                  <Card>
                    <CardContent className="pt-6 space-y-8">
                      <Section
                        title="Telephony Provider"
                        description="Choose the telephony provider and enter your credentials."
                      >
                        {/* Provider toggle */}
                        <div className="flex items-center gap-3">
                          <Label className="text-sm text-muted-foreground">
                            Provider
                          </Label>
                          <div className="flex gap-1 rounded-lg border p-0.5">
                            {(["plivo", "twilio"] as const).map((p) => (
                              <button
                                key={p}
                                type="button"
                                onClick={() =>
                                  setField("telephony_provider", p)
                                }
                                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
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

                        <Separator />

                        {/* Plivo fields */}
                        {form.telephony_provider === "plivo" ? (
                          <div className="space-y-4">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <Label htmlFor="plivo_auth_id">
                                  Auth ID{" "}
                                  {isNew && (
                                    <span className="text-destructive">*</span>
                                  )}
                                </Label>
                                <Input
                                  id="plivo_auth_id"
                                  value={form.plivo_auth_id}
                                  onChange={(e) =>
                                    setField("plivo_auth_id", e.target.value)
                                  }
                                  placeholder={
                                    !isNew ? "(unchanged)" : "Your Plivo Auth ID"
                                  }
                                  className="font-mono text-sm"
                                />
                                {!isNew && (
                                  <p className="text-xs text-muted-foreground">
                                    Leave blank to keep existing value.
                                  </p>
                                )}
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor="plivo_auth_token">
                                  Auth Token{" "}
                                  {isNew && (
                                    <span className="text-destructive">*</span>
                                  )}
                                </Label>
                                <Input
                                  id="plivo_auth_token"
                                  type="password"
                                  value={form.plivo_auth_token}
                                  onChange={(e) =>
                                    setField(
                                      "plivo_auth_token",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={
                                    !isNew ? "(unchanged)" : "Your Plivo Auth Token"
                                  }
                                  className="font-mono text-sm"
                                />
                                {!isNew && (
                                  <p className="text-xs text-muted-foreground">
                                    Leave blank to keep existing value.
                                  </p>
                                )}
                              </div>
                            </div>
                            <div className="space-y-2">
                              <Label htmlFor="plivo_caller_id">
                                Caller ID{" "}
                                {isNew && (
                                  <span className="text-destructive">*</span>
                                )}
                              </Label>
                              <Input
                                id="plivo_caller_id"
                                value={form.plivo_caller_id}
                                onChange={(e) =>
                                  setField("plivo_caller_id", e.target.value)
                                }
                                placeholder="+14155551234"
                                className="font-mono text-sm max-w-xs"
                              />
                              <p className="text-xs text-muted-foreground">
                                The phone number displayed as the caller.
                              </p>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-4">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <Label htmlFor="twilio_account_sid">
                                  Account SID{" "}
                                  {isNew && (
                                    <span className="text-destructive">*</span>
                                  )}
                                </Label>
                                <Input
                                  id="twilio_account_sid"
                                  value={form.twilio_account_sid}
                                  onChange={(e) =>
                                    setField(
                                      "twilio_account_sid",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={
                                    !isNew ? "(unchanged)" : "Your Twilio Account SID"
                                  }
                                  className="font-mono text-sm"
                                />
                                {!isNew && (
                                  <p className="text-xs text-muted-foreground">
                                    Leave blank to keep existing value.
                                  </p>
                                )}
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor="twilio_auth_token">
                                  Auth Token{" "}
                                  {isNew && (
                                    <span className="text-destructive">*</span>
                                  )}
                                </Label>
                                <Input
                                  id="twilio_auth_token"
                                  type="password"
                                  value={form.twilio_auth_token}
                                  onChange={(e) =>
                                    setField(
                                      "twilio_auth_token",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={
                                    !isNew ? "(unchanged)" : "Your Twilio Auth Token"
                                  }
                                  className="font-mono text-sm"
                                />
                                {!isNew && (
                                  <p className="text-xs text-muted-foreground">
                                    Leave blank to keep existing value.
                                  </p>
                                )}
                              </div>
                            </div>
                            <div className="space-y-2">
                              <Label htmlFor="twilio_phone_number">
                                Phone Number{" "}
                                {isNew && (
                                  <span className="text-destructive">*</span>
                                )}
                              </Label>
                              <Input
                                id="twilio_phone_number"
                                value={form.twilio_phone_number}
                                onChange={(e) =>
                                  setField(
                                    "twilio_phone_number",
                                    e.target.value,
                                  )
                                }
                                placeholder="+14155551234"
                                className="font-mono text-sm max-w-xs"
                              />
                              <p className="text-xs text-muted-foreground">
                                Your Twilio phone number for outbound calls.
                              </p>
                            </div>
                          </div>
                        )}
                      </Section>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* ================================================================
                    TAB 4: Integrations
                   ================================================================ */}
                <TabsContent value="integrations">
                  <div className="space-y-6">
                    {/* GHL Credentials */}
                    <Card>
                      <CardContent className="pt-6 space-y-8">
                        <Section
                          title="GoHighLevel"
                          description="Connect your CRM for post-call tagging and workflow triggers."
                        >
                          <div className="space-y-4">
                            <div className="space-y-2">
                              <Label htmlFor="ghl_webhook_url">
                                Webhook URL
                              </Label>
                              <Input
                                id="ghl_webhook_url"
                                value={form.ghl_webhook_url}
                                onChange={(e) =>
                                  setField("ghl_webhook_url", e.target.value)
                                }
                                placeholder="https://services.leadconnectorhq.com/hooks/..."
                                className="font-mono text-sm"
                              />
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <Label htmlFor="ghl_api_key">API Key</Label>
                                <Input
                                  id="ghl_api_key"
                                  type="password"
                                  value={form.ghl_api_key}
                                  onChange={(e) =>
                                    setField("ghl_api_key", e.target.value)
                                  }
                                  placeholder={
                                    !isNew ? "(unchanged)" : "Your GHL API key"
                                  }
                                  className="font-mono text-sm"
                                />
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor="ghl_location_id">
                                  Location ID
                                </Label>
                                <Input
                                  id="ghl_location_id"
                                  value={form.ghl_location_id}
                                  onChange={(e) =>
                                    setField(
                                      "ghl_location_id",
                                      e.target.value,
                                    )
                                  }
                                  placeholder="e.g. abc123XYZ"
                                  className="font-mono text-sm"
                                />
                              </div>
                            </div>
                            <div className="space-y-2">
                              <Label htmlFor="ghl_post_call_tag">
                                Post-Call Tag
                              </Label>
                              <Input
                                id="ghl_post_call_tag"
                                value={form.ghl_post_call_tag}
                                onChange={(e) =>
                                  setField(
                                    "ghl_post_call_tag",
                                    e.target.value,
                                  )
                                }
                                placeholder="wavelength-called"
                                className="font-mono text-sm max-w-xs"
                              />
                              <p className="text-xs text-muted-foreground">
                                Tag added to the CRM contact after every
                                completed call.
                              </p>
                            </div>
                          </div>
                        </Section>
                      </CardContent>
                    </Card>

                    {/* CRM Workflow Triggers */}
                    <Card>
                      <CardContent className="pt-6 space-y-6">
                        <div className="flex items-center justify-between">
                          <div>
                            <h3 className="text-sm font-semibold">
                              CRM Workflow Triggers
                            </h3>
                            <p className="text-xs text-muted-foreground mt-0.5">
                              Each workflow adds a tag to the contact. Set up
                              CRM automations to trigger on &quot;tag
                              added&quot;.
                            </p>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={addWorkflow}
                          >
                            <Plus className="h-3.5 w-3.5 mr-1" />
                            Add Workflow
                          </Button>
                        </div>

                        {form.ghl_workflows.length === 0 && (
                          <div className="rounded-lg border border-dashed p-8 text-center">
                            <p className="text-sm text-muted-foreground">
                              No workflows configured yet.
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              Add a workflow to trigger CRM automations based
                              on call events.
                            </p>
                          </div>
                        )}

                        {form.ghl_workflows.map((wf) => (
                          <div
                            key={wf.id}
                            className="rounded-lg border p-4 space-y-3"
                          >
                            <div className="flex items-center gap-3">
                              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
                                <Input
                                  value={wf.name}
                                  onChange={(e) =>
                                    updateWorkflow(wf.id, {
                                      name: e.target.value,
                                    })
                                  }
                                  placeholder="Workflow Name"
                                  className="h-8 text-sm"
                                />
                                <Input
                                  value={wf.tag}
                                  onChange={(e) =>
                                    updateWorkflow(wf.id, {
                                      tag: e.target.value,
                                    })
                                  }
                                  placeholder="CRM Tag"
                                  className="h-8 text-sm font-mono"
                                />
                              </div>
                              <div className="flex items-center gap-2">
                                <Switch
                                  checked={wf.enabled}
                                  onCheckedChange={(checked) =>
                                    updateWorkflow(wf.id, {
                                      enabled: checked,
                                    })
                                  }
                                />
                                <span className="text-xs text-muted-foreground w-6">
                                  {wf.enabled ? "On" : "Off"}
                                </span>
                              </div>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 shrink-0"
                                onClick={() => removeWorkflow(wf.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>

                            <div className="flex items-center gap-1">
                              <span className="text-xs text-muted-foreground mr-2">
                                Timing
                              </span>
                              {TIMING_OPTIONS.map((opt) => (
                                <Button
                                  key={opt.value}
                                  variant={
                                    wf.timing === opt.value
                                      ? "default"
                                      : "outline"
                                  }
                                  size="sm"
                                  className="h-7 text-xs px-3"
                                  onClick={() =>
                                    updateWorkflow(wf.id, {
                                      timing: opt.value,
                                    })
                                  }
                                >
                                  {opt.label}
                                </Button>
                              ))}
                            </div>

                            {wf.timing === "during_call" && (
                              <div className="space-y-1.5">
                                <Label className="text-xs">
                                  AI Trigger Description
                                </Label>
                                <Textarea
                                  value={wf.trigger_description || ""}
                                  onChange={(e) =>
                                    updateWorkflow(wf.id, {
                                      trigger_description: e.target.value,
                                    })
                                  }
                                  placeholder="e.g. Trigger when the customer confirms they want more information about the course."
                                  className="min-h-[60px] text-sm"
                                />
                                <p className="text-xs text-muted-foreground">
                                  Describe the condition for the AI to
                                  trigger this workflow mid-call.
                                </p>
                              </div>
                            )}
                          </div>
                        ))}
                      </CardContent>
                    </Card>

                    {/* API Trigger */}
                    {!isNew && (
                      <Card>
                        <CardContent className="pt-6">
                          <Section
                            title="API Trigger"
                            description="Use this cURL to trigger calls from external systems like GoHighLevel."
                          >
                            <div className="space-y-3">
                              <div className="relative">
                                <pre className="bg-muted rounded-lg p-4 text-xs overflow-x-auto whitespace-pre-wrap break-all font-mono">
                                  {`curl -X POST '${typeof window !== "undefined" ? window.location.origin : ""}/api/webhook/trigger-call' \\
  -H 'Content-Type: application/json' \\
  -H 'x-api-key: YOUR_WEBHOOK_API_KEY' \\
  -d '${JSON.stringify(
    {
      phoneNumber: "+1234567890",
      contactName: "John Doe",
      botConfigId: botId,
      customVariableOverrides: {
        agent_name: form.agent_name,
        company_name: form.company_name,
        ...(form.event_name ? { event_name: form.event_name } : {}),
        ...(form.location ? { location: form.location } : {}),
        ...Object.fromEntries(
          form.ghl_workflows
            .filter((w: GHLWorkflow) => w.name)
            .map(() => [] as string[])
        ),
      },
    },
    null,
    2,
  )}'`}
                                </pre>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="absolute top-2 right-2 h-7 gap-1 text-xs"
                                  onClick={() => {
                                    const curl = `curl -X POST '${window.location.origin}/api/webhook/trigger-call' \\\n  -H 'Content-Type: application/json' \\\n  -H 'x-api-key: YOUR_WEBHOOK_API_KEY' \\\n  -d '${JSON.stringify({ phoneNumber: "+1234567890", contactName: "John Doe", botConfigId: botId, customVariableOverrides: { agent_name: form.agent_name, company_name: form.company_name } }, null, 2)}'`;
                                    navigator.clipboard.writeText(curl);
                                    setCopiedCurl(true);
                                    toast.success("cURL copied");
                                    setTimeout(() => setCopiedCurl(false), 2000);
                                  }}
                                >
                                  {copiedCurl ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                                  {copiedCurl ? "Copied" : "Copy"}
                                </Button>
                              </div>
                              <div className="space-y-1.5 text-sm text-muted-foreground">
                                <p><strong className="text-foreground">phoneNumber</strong> — Contact phone number with country code</p>
                                <p><strong className="text-foreground">contactName</strong> — Contact&apos;s name</p>
                                <p><strong className="text-foreground">customVariableOverrides</strong> — Override prompt variables per call</p>
                              </div>
                              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
                                Replace <code className="font-mono bg-muted px-1 rounded">YOUR_WEBHOOK_API_KEY</code> with your server&apos;s <code className="font-mono bg-muted px-1 rounded">WEBHOOK_API_KEY</code> env variable.
                              </div>
                            </div>
                          </Section>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </TabsContent>

                {/* ================================================================
                    TAB 5: Settings
                   ================================================================ */}
                <TabsContent value="settings">
                  <Card>
                    <CardContent className="pt-6 space-y-8">
                      <Section
                        title="Call Limits"
                        description="Control the maximum duration and timeout behavior for calls."
                      >
                        <div className="space-y-6">
                          {/* Max call duration */}
                          <div className="flex items-center justify-between rounded-lg border p-4">
                            <div className="space-y-1">
                              <p className="text-sm font-medium">
                                Max Call Duration
                              </p>
                              <p className="text-xs text-muted-foreground">
                                Maximum duration (in minutes) before the bot
                                wraps up the call.
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Input
                                type="number"
                                value={Math.round(form.max_call_duration / 60)}
                                onChange={(e) =>
                                  setField(
                                    "max_call_duration",
                                    (parseInt(e.target.value) || 0) * 60,
                                  )
                                }
                                min={1}
                                max={60}
                                className="w-20 text-center"
                              />
                              <span className="text-sm text-muted-foreground">
                                min
                              </span>
                            </div>
                          </div>

                          {/* Silence timeout */}
                          <div className="flex items-center justify-between rounded-lg border p-4">
                            <div className="space-y-1">
                              <p className="text-sm font-medium">
                                Silence Timeout
                              </p>
                              <p className="text-xs text-muted-foreground">
                                Seconds of silence before the bot prompts the
                                user or ends the call.
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Input
                                type="number"
                                value={form.silence_timeout_secs}
                                onChange={(e) =>
                                  setField(
                                    "silence_timeout_secs",
                                    parseInt(e.target.value) || 0,
                                  )
                                }
                                min={1}
                                max={30}
                                className="w-20 text-center"
                              />
                              <span className="text-sm text-muted-foreground">
                                sec
                              </span>
                            </div>
                          </div>
                        </div>
                      </Section>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          </ScrollArea>

          {/* Sticky footer save bar */}
          <div className="border-t border-border/50 bg-background/80 backdrop-blur-md px-6 py-3 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {isNew
                ? "Fill in the required fields and save to create your bot."
                : "Changes are saved when you click Save."}
            </p>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                onClick={() => router.push("/bots")}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="min-w-[100px]"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    Save
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </PageTransition>
    </>
  );
}
