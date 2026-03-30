"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
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
  Target,
  AlertTriangle,
  Database,
  Undo2,
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

import { useAuth } from "@/contexts/auth-context";
import { useBot, useBots, useCreateBot, useUpdateBot } from "@/hooks/use-bots";
import { usePhoneNumbers } from "@/hooks/use-settings";
import { GEMINI_VOICE_GROUPS, SARVAM_VOICE_GROUPS, ELEVENLABS_VOICE_GROUPS, SARVAM_LANGUAGE_OPTIONS, DEEPGRAM_LANGUAGE_OPTIONS, BUILTIN_VARIABLES, TTS_PROVIDER_OPTIONS, STT_PROVIDER_OPTIONS, STT_PROVIDER_OPTIONS_CLIENT, LLM_PROVIDER_OPTIONS, LLM_MODEL_OPTIONS } from "@/lib/constants";
import type { BotConfig, GHLWorkflow, GoalConfig, SuccessCriterion, RedFlagConfig, DataCaptureField, CallbackSchedule, RetryStep, N8nAutomation, N8nCondition } from "@/types/api";
import { fetchTemplates, type SequenceTemplate } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Retry schedule templates
// ---------------------------------------------------------------------------

const RETRY_TEMPLATES: Record<string, { label: string; description: string; steps: RetryStep[] }> = {
  standard: {
    label: "Standard",
    description: "3h, 3h, next day midday, next day evening",
    steps: [
      { delay_hours: 3 },
      { delay_hours: 3 },
      { delay_type: "next_day", preferred_window: [11, 13] },
      { delay_type: "next_day", preferred_window: [20, 22] },
    ],
  },
  aggressive: {
    label: "Aggressive",
    description: "1h, 2h, 3h, next day evening, next day midday",
    steps: [
      { delay_hours: 1 },
      { delay_hours: 2 },
      { delay_hours: 3 },
      { delay_type: "next_day", preferred_window: [20, 22] },
      { delay_type: "next_day", preferred_window: [11, 13] },
    ],
  },
  relaxed: {
    label: "Relaxed",
    description: "Next day midday, next day evening, next day midday",
    steps: [
      { delay_type: "next_day", preferred_window: [11, 13] },
      { delay_type: "next_day", preferred_window: [20, 22] },
      { delay_type: "next_day", preferred_window: [11, 13] },
    ],
  },
};

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
  greeting_template: string;
  callback_greeting_template: string;
  stt_provider: "deepgram" | "sarvam" | "smallest";
  tts_provider: "gemini" | "sarvam" | "elevenlabs";
  tts_voice: string;
  tts_style_prompt: string;
  llm_provider: "google" | "groq";
  llm_model: string;
  llm_thinking_enabled: boolean;
  language: string;
  allowed_languages: string[];
  system_prompt_template: string;
  context_variables: Record<string, string>;
  silence_timeout_secs: number;
  ghl_webhook_url: string;
  ghl_post_call_tag: string;
  ghl_workflows: GHLWorkflow[];
  n8n_automations: N8nAutomation[];
  max_call_duration: number;
  telephony_provider: "plivo" | "twilio";
  phone_number_id: string | null;
  plivo_caller_id: string;
  twilio_phone_number: string;
  max_concurrent_calls: number;
  circuit_breaker_enabled: boolean;
  circuit_breaker_threshold: number;
  ambient_sound_enabled: boolean;
  callback_enabled: boolean;
  callback_retry_delay_hours: number;
  callback_max_retries: number;
  callback_timezone: string;
  callback_window_start: number;
  callback_window_end: number;
  callback_schedule: CallbackSchedule | null;
  call_memory_enabled: boolean;
  call_memory_count: number;
  bot_switch_targets: BotSwitchTarget[];
  sequence_template_id: string | null;
}

interface BotSwitchTarget {
  id: string;
  target_bot_id: string;
  description: string;
}

const EMPTY_FORM: BotForm = {
  agent_name: "",
  company_name: "",
  location: "",
  event_name: "",
  event_date: "",
  event_time: "",
  greeting_template: "",
  callback_greeting_template: "",
  stt_provider: "deepgram",
  tts_provider: "sarvam",
  tts_voice: "priya",
  tts_style_prompt: "",
  llm_provider: "google",
  llm_model: "gemini-2.5-flash",
  llm_thinking_enabled: false,
  language: "en-IN",
  allowed_languages: [],
  system_prompt_template: "",
  context_variables: {},
  silence_timeout_secs: 5,
  ghl_webhook_url: "",
  ghl_post_call_tag: "",
  ghl_workflows: [],
  n8n_automations: [],
  max_call_duration: 480,
  telephony_provider: "plivo",
  phone_number_id: null,
  plivo_caller_id: "",
  twilio_phone_number: "",
  max_concurrent_calls: 5,
  circuit_breaker_enabled: true,
  circuit_breaker_threshold: 3,
  ambient_sound_enabled: true,
  callback_enabled: false,
  callback_retry_delay_hours: 2,
  callback_max_retries: 3,
  callback_timezone: "Asia/Kolkata",
  callback_window_start: 9,
  callback_window_end: 20,
  callback_schedule: null,
  call_memory_enabled: false,
  call_memory_count: 3,
  bot_switch_targets: [],
  sequence_template_id: null,
};

const TIMING_OPTIONS = [
  { value: "pre_call", label: "Pre-Call" },
  { value: "during_call", label: "During Call" },
  { value: "post_call", label: "Post-Call" },
] as const;

// ---------------------------------------------------------------------------
// Severity badge colors for red flags
// ---------------------------------------------------------------------------

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
  high: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  medium: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  low: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

// ---------------------------------------------------------------------------
// Tab descriptions
// ---------------------------------------------------------------------------

const TAB_DESCRIPTIONS: Record<string, string> = {
  general: "Set up your agent's identity, greeting message, and optional event or location context.",
  "voice-prompt": "Configure voice personality, speech recognition, language, and the system prompt that drives your agent's behavior.",
  telephony: "Choose the telephony provider for outbound calls. Credentials are managed in account settings.",
  integrations: "Connect your bot to GoHighLevel for CRM tagging, workflow triggers, and external API access.",
  goals: "Define call objectives, success criteria, red flags, and structured data to capture from conversations.",
  settings: "Fine-tune call duration limits, silence timeouts, and circuit breaker thresholds.",
};

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
    greeting_template: bot.greeting_template || "",
    callback_greeting_template: bot.callback_greeting_template || "",
    stt_provider: bot.stt_provider || "deepgram",
    tts_provider: (bot.tts_provider as "gemini" | "sarvam" | "elevenlabs") || "sarvam",
    tts_voice: bot.tts_voice,
    tts_style_prompt: bot.tts_style_prompt || "",
    llm_provider: bot.llm_provider || "google",
    llm_model: bot.llm_model || "gemini-2.5-flash",
    llm_thinking_enabled: bot.llm_thinking_enabled ?? false,
    language: bot.language || "en-IN",
    allowed_languages: bot.allowed_languages || [],
    system_prompt_template: bot.system_prompt_template,
    context_variables: bot.context_variables || {},
    silence_timeout_secs: bot.silence_timeout_secs,
    ghl_webhook_url: bot.ghl_webhook_url || "",
    ghl_post_call_tag: bot.ghl_post_call_tag || "",
    ghl_workflows: bot.ghl_workflows || [],
    n8n_automations: bot.n8n_automations || [],
    max_call_duration: bot.max_call_duration ?? 480,
    telephony_provider: bot.telephony_provider || "plivo",
    phone_number_id: bot.phone_number_id || null,
    plivo_caller_id: bot.plivo_caller_id,
    twilio_phone_number: bot.twilio_phone_number || "",
    max_concurrent_calls: bot.max_concurrent_calls ?? 5,
    circuit_breaker_enabled: bot.circuit_breaker_enabled ?? true,
    circuit_breaker_threshold: bot.circuit_breaker_threshold ?? 3,
    ambient_sound_enabled: bot.ambient_sound != null,
    callback_enabled: bot.callback_enabled ?? false,
    callback_retry_delay_hours: bot.callback_retry_delay_hours ?? 2,
    callback_max_retries: bot.callback_max_retries ?? 3,
    callback_timezone: bot.callback_timezone || "Asia/Kolkata",
    callback_window_start: bot.callback_window_start ?? 9,
    callback_window_end: bot.callback_window_end ?? 20,
    callback_schedule: (bot as any).callback_schedule || (bot.callback_enabled && (bot.callback_max_retries ?? 0) > 0
      ? {
          template: "custom" as const,
          steps: Array.from({ length: bot.callback_max_retries ?? 3 }, () => ({
            delay_hours: bot.callback_retry_delay_hours ?? 2,
          })),
        }
      : null),
    call_memory_enabled: bot.call_memory_enabled ?? false,
    call_memory_count: bot.call_memory_count ?? 3,
    bot_switch_targets: bot.bot_switch_targets || [],
    sequence_template_id: bot.sequence_template_id || null,
  };
}

/** Deep-compare two form snapshots (ignoring reference equality). */
function formsEqual(a: BotForm, b: BotForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
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
// Loading skeleton that matches the form layout
// ---------------------------------------------------------------------------

function BotEditorSkeleton() {
  return (
    <>
      <Header title="Loading..." />
      <PageTransition>
        <div className="flex flex-col h-[calc(100vh-3.5rem)]">
          {/* Top bar skeleton */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-9 rounded-lg" />
              <div className="space-y-1.5">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-3 w-24" />
              </div>
            </div>
            <Skeleton className="h-9 w-[100px] rounded-md" />
          </div>

          {/* Content skeleton */}
          <div className="flex-1 overflow-hidden">
            <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
              {/* Tab bar skeleton */}
              <div className="flex gap-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-24 rounded-md" />
                ))}
              </div>

              {/* Tab description skeleton */}
              <Skeleton className="h-4 w-96" />

              {/* Card skeleton matching General tab */}
              <div className="rounded-lg border border-border/50 p-6 space-y-6">
                {/* Section header */}
                <div className="space-y-1">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-64" />
                </div>
                {/* Two column fields */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="h-9 w-full rounded-md" />
                  </div>
                  <div className="space-y-2">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-9 w-full rounded-md" />
                  </div>
                </div>

                <Skeleton className="h-px w-full" />

                {/* Greeting section */}
                <div className="space-y-1">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-3 w-80" />
                </div>
                <div className="space-y-2">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-9 w-full rounded-md" />
                </div>

                <Skeleton className="h-px w-full" />

                {/* Location & Event */}
                <div className="space-y-1">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-72" />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="space-y-2">
                      <Skeleton className="h-3 w-20" />
                      <Skeleton className="h-9 w-full rounded-md" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Footer skeleton */}
          <div className="border-t border-border/50 px-6 py-3 flex items-center justify-between">
            <Skeleton className="h-3 w-64" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-20 rounded-md" />
              <Skeleton className="h-9 w-[100px] rounded-md" />
            </div>
          </div>
        </div>
      </PageTransition>
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BotEditorPage() {
  const router = useRouter();
  const params = useParams();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const botId = params.botId as string;
  const isNew = botId === "new";

  // ---- React Query hooks ----
  const { data: botData, isLoading: botLoading, isError: botError } = useBot(botId);
  const { data: allBots } = useBots();
  const [sequenceTemplates, setSequenceTemplates] = useState<SequenceTemplate[]>([]);
  useEffect(() => {
    fetchTemplates(1, 100).then((data) => setSequenceTemplates(data.items)).catch(() => {});
  }, []);
  const createBotMutation = useCreateBot();
  const updateBotMutation = useUpdateBot();
  const { data: phoneNumbers } = usePhoneNumbers();
  const saving = createBotMutation.isPending || updateBotMutation.isPending;

  const [form, setForm] = useState<BotForm>(EMPTY_FORM);
  const [goalConfig, setGoalConfig] = useState<GoalConfig | null>(null);
  const [copiedCurl, setCopiedCurl] = useState(false);
  const [newVarName, setNewVarName] = useState("");
  const [activeTab, setActiveTab] = useState("general");

  // Track the "saved" snapshot for unsaved-changes detection
  const [savedForm, setSavedForm] = useState<BotForm>(EMPTY_FORM);
  const [savedGoalConfig, setSavedGoalConfig] = useState<GoalConfig | null>(null);

  const hasUnsavedChanges = useMemo(() => {
    const formChanged = !formsEqual(form, savedForm);
    const goalChanged = JSON.stringify(goalConfig) !== JSON.stringify(savedGoalConfig);
    return formChanged || goalChanged;
  }, [form, savedForm, goalConfig, savedGoalConfig]);

  // ---- Populate form from React Query data ----

  const hasHydrated = useRef(false);
  useEffect(() => {
    if (botData && !hasHydrated.current) {
      const formData = botToForm(botData);
      setForm(formData);
      setSavedForm(formData);
      const gc = botData.goal_config || null;
      setGoalConfig(gc);
      setSavedGoalConfig(gc);
      hasHydrated.current = true;
    }
  }, [botData]);

  // Handle fetch error
  useEffect(() => {
    if (botError) {
      toast.error("Failed to load bot configuration");
      router.push("/bots");
    }
  }, [botError, router]);

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

  // ---- n8n automation helpers ----

  function addN8nAutomation() {
    setForm((prev) => ({
      ...prev,
      n8n_automations: [
        ...prev.n8n_automations,
        {
          id: crypto.randomUUID(),
          name: "",
          webhook_url: "",
          timing: "post_call" as const,
          enabled: true,
          conditions: [],
          condition_logic: "all" as const,
          payload_sections: ["call", "analysis", "contact", "bot_config"],
          include_transcript: false,
          custom_fields: {},
        },
      ],
    }));
  }

  function updateN8nAutomation(id: string, updates: Partial<N8nAutomation>) {
    setForm((prev) => ({
      ...prev,
      n8n_automations: prev.n8n_automations.map((a) =>
        a.id === id ? { ...a, ...updates } : a,
      ),
    }));
  }

  function removeN8nAutomation(id: string) {
    setForm((prev) => ({
      ...prev,
      n8n_automations: prev.n8n_automations.filter((a) => a.id !== id),
    }));
  }

  function addN8nCondition(automationId: string) {
    setForm((prev) => ({
      ...prev,
      n8n_automations: prev.n8n_automations.map((a) =>
        a.id === automationId
          ? { ...a, conditions: [...a.conditions, { field: "goal_outcome", operator: "equals" as const, value: "" }] }
          : a,
      ),
    }));
  }

  function updateN8nCondition(automationId: string, conditionIndex: number, updates: Partial<N8nCondition>) {
    setForm((prev) => ({
      ...prev,
      n8n_automations: prev.n8n_automations.map((a) =>
        a.id === automationId
          ? {
              ...a,
              conditions: a.conditions.map((c, i) =>
                i === conditionIndex ? { ...c, ...updates } : c,
              ),
            }
          : a,
      ),
    }));
  }

  function removeN8nCondition(automationId: string, conditionIndex: number) {
    setForm((prev) => ({
      ...prev,
      n8n_automations: prev.n8n_automations.map((a) =>
        a.id === automationId
          ? { ...a, conditions: a.conditions.filter((_, i) => i !== conditionIndex) }
          : a,
      ),
    }));
  }

  // ---- Bot switch target helpers ----

  function addSwitchTarget() {
    setForm((prev) => ({
      ...prev,
      bot_switch_targets: [
        ...prev.bot_switch_targets,
        {
          id: crypto.randomUUID(),
          target_bot_id: "",
          description: "",
        },
      ],
    }));
  }

  function updateSwitchTarget(id: string, updates: Partial<BotSwitchTarget>) {
    setForm((prev) => ({
      ...prev,
      bot_switch_targets: prev.bot_switch_targets.map((t) =>
        t.id === id ? { ...t, ...updates } : t,
      ),
    }));
  }

  function removeSwitchTarget(id: string) {
    setForm((prev) => ({
      ...prev,
      bot_switch_targets: prev.bot_switch_targets.filter((t) => t.id !== id),
    }));
  }

  // ---- Goal config helpers ----

  function initGoalConfig() {
    setGoalConfig({
      version: 1,
      goal_type: "",
      goal_description: "",
      success_criteria: [{ id: "primary", label: "", is_primary: true }],
      red_flags: [],
      data_capture_fields: [],
    });
  }

  function updateGoalField<K extends keyof GoalConfig>(key: K, value: GoalConfig[K]) {
    setGoalConfig((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function addSuccessCriterion() {
    if (!goalConfig) return;
    updateGoalField("success_criteria", [
      ...goalConfig.success_criteria,
      { id: `criterion_${Date.now()}`, label: "", is_primary: false },
    ]);
  }

  function updateCriterion(index: number, updates: Partial<SuccessCriterion>) {
    if (!goalConfig) return;
    const updated = goalConfig.success_criteria.map((c, i) => {
      if (i !== index) return updates.is_primary ? { ...c, is_primary: false } : c;
      return { ...c, ...updates };
    });
    updateGoalField("success_criteria", updated);
  }

  function removeCriterion(index: number) {
    if (!goalConfig) return;
    updateGoalField(
      "success_criteria",
      goalConfig.success_criteria.filter((_, i) => i !== index),
    );
  }

  function addRedFlag() {
    if (!goalConfig) return;
    updateGoalField("red_flags", [
      ...(goalConfig.red_flags || []),
      { id: `flag_${Date.now()}`, label: "", severity: "medium" as const, detect_in: "post_call" as const },
    ]);
  }

  function updateRedFlag(index: number, updates: Partial<RedFlagConfig>) {
    if (!goalConfig) return;
    const updated = (goalConfig.red_flags || []).map((f, i) =>
      i === index ? { ...f, ...updates } : f,
    );
    updateGoalField("red_flags", updated);
  }

  function removeRedFlag(index: number) {
    if (!goalConfig) return;
    updateGoalField(
      "red_flags",
      (goalConfig.red_flags || []).filter((_, i) => i !== index),
    );
  }

  function addCaptureField() {
    if (!goalConfig) return;
    updateGoalField("data_capture_fields", [
      ...(goalConfig.data_capture_fields || []),
      { id: `field_${Date.now()}`, label: "", type: "string" as const },
    ]);
  }

  function updateCaptureField(index: number, updates: Partial<DataCaptureField>) {
    if (!goalConfig) return;
    const updated = (goalConfig.data_capture_fields || []).map((f, i) =>
      i === index ? { ...f, ...updates } : f,
    );
    updateGoalField("data_capture_fields", updated);
  }

  function removeCaptureField(index: number) {
    if (!goalConfig) return;
    updateGoalField(
      "data_capture_fields",
      (goalConfig.data_capture_fields || []).filter((_, i) => i !== index),
    );
  }

  // ---- Discard changes ----

  function discardChanges() {
    setForm(savedForm);
    setGoalConfig(savedGoalConfig);
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

    // Telephony credentials are now at the account level (Settings page)

    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(form)) {
        if (k === "context_variables" || k === "ghl_workflows" || k === "n8n_automations" || k === "allowed_languages" || k === "bot_switch_targets") {
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

      // Transform ambient toggle to API fields
      if (form.ambient_sound_enabled) {
        payload.ambient_sound = "office_hum";
        payload.ambient_sound_volume = 0.18;
      } else {
        payload.ambient_sound = null;
        payload.ambient_sound_volume = null;
      }
      delete payload.ambient_sound_enabled;

      // Include goal_config in payload — sanitize enum fields
      if (goalConfig) {
        payload.goal_config = {
          ...goalConfig,
          data_capture_fields: (goalConfig.data_capture_fields || []).map((f) => {
            if (f.type === "enum") {
              return { ...f, enum_values: f.enum_values?.length ? f.enum_values : ["yes", "no"] };
            }
            const { enum_values, ...rest } = f;
            return rest;
          }),
        };
      } else {
        payload.goal_config = null;
      }

      if (isNew) {
        await createBotMutation.mutateAsync(payload as never);
        toast.success("Bot created successfully");
      } else {
        await updateBotMutation.mutateAsync({ id: botId, data: payload as never });
        toast.success("Bot updated successfully");
      }

      // Update saved snapshot so unsaved indicator clears
      setSavedForm(form);
      setSavedGoalConfig(goalConfig);

      router.push("/bots");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save bot");
    }
  }

  // ---- Loading skeleton ----

  if (!isNew && botLoading) {
    return <BotEditorSkeleton />;
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
              <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                <TabsList className="w-full justify-start mb-4">
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
                  <TabsTrigger value="goals" className="gap-1.5">
                    <Target className="h-3.5 w-3.5" />
                    Goals
                  </TabsTrigger>
                  <TabsTrigger value="settings" className="gap-1.5">
                    <Settings className="h-3.5 w-3.5" />
                    Settings
                  </TabsTrigger>
                </TabsList>

                {/* Tab description */}
                <p className="text-sm text-muted-foreground mb-6">
                  {TAB_DESCRIPTIONS[activeTab] || ""}
                </p>

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
                        title="Greeting"
                        description="The opening line when the bot calls. Leave blank for the default greeting."
                      >
                        <div className="space-y-2">
                          <Label htmlFor="greeting_template">
                            Greeting Template
                          </Label>
                          <Input
                            id="greeting_template"
                            value={form.greeting_template}
                            onChange={(e) =>
                              setField("greeting_template", e.target.value)
                            }
                            placeholder="Hi {contact_name}, this is {agent_name} calling from {company_name}. How are you doing today?"
                          />
                          <p className="text-xs text-muted-foreground">
                            Available variables: {"{contact_name}"}, {"{agent_name}"}, {"{company_name}"}, {"{event_name}"}, {"{event_date}"}, {"{event_time}"}, {"{location}"}
                          </p>
                        </div>

                        <div className="space-y-2 mt-4">
                          <Label htmlFor="callback_greeting_template">
                            Callback Greeting (Returning Callers)
                          </Label>
                          <Input
                            id="callback_greeting_template"
                            value={form.callback_greeting_template}
                            onChange={(e) =>
                              setField("callback_greeting_template", e.target.value)
                            }
                            placeholder="Hi {contact_name}, this is {agent_name} again from {company_name}. Good to connect with you again!"
                          />
                          <p className="text-xs text-muted-foreground">
                            Used when calling someone who has been called before (when call memory is active). Same variables available.
                          </p>
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
                          description="Choose the voice personality, speech recognition model, and language for your agent."
                        >
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                            <div className="space-y-2">
                              <Label>{isSuperAdmin ? "STT Provider" : "Speech Recognition"}</Label>
                              <Select
                                value={form.stt_provider}
                                onValueChange={(v) => {
                                  setField("stt_provider", v as "deepgram" | "sarvam" | "smallest");
                                  // Reset language to provider default
                                  setField("language", v === "deepgram" ? "multi" : v === "smallest" ? "en" : "unknown");
                                }}
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="Select model..." />
                                </SelectTrigger>
                                <SelectContent>
                                  {(isSuperAdmin ? STT_PROVIDER_OPTIONS : STT_PROVIDER_OPTIONS_CLIENT).map((p) => (
                                    <SelectItem key={p.value} value={p.value}>
                                      {p.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            {isSuperAdmin && (
                              <div className="space-y-2">
                                <Label>TTS Provider</Label>
                                <Select
                                  value={form.tts_provider}
                                  onValueChange={(v) => {
                                    setField("tts_provider", v as "gemini" | "sarvam" | "elevenlabs");
                                    // Reset voice to provider default
                                    setField("tts_voice", v === "sarvam" ? "priya" : v === "elevenlabs" ? "90ipbRoKi4CpHXvKVtl0" : "Kore");
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
                            )}
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
                                  {(isSuperAdmin
                                    ? (form.tts_provider === "elevenlabs" ? ELEVENLABS_VOICE_GROUPS : form.tts_provider === "gemini" ? GEMINI_VOICE_GROUPS : SARVAM_VOICE_GROUPS)
                                    : SARVAM_VOICE_GROUPS
                                  ).map((group) => (
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
                                  {(form.stt_provider === "deepgram" ? DEEPGRAM_LANGUAGE_OPTIONS : SARVAM_LANGUAGE_OPTIONS).map((l) => (
                                    <SelectItem key={l.value} value={l.value}>
                                      {l.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          </div>

                        </Section>

                        {isSuperAdmin && (
                          <>
                            <Separator />

                            <Section
                              title="LLM"
                              description="Choose the LLM provider and model for conversation intelligence."
                            >
                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-2">
                                  <Label>LLM Provider</Label>
                                  <Select
                                    value={form.llm_provider}
                                    onValueChange={(v) => {
                                      const provider = v as "google" | "groq";
                                      setField("llm_provider", provider);
                                      // Reset model to provider default
                                      const defaultModel = LLM_MODEL_OPTIONS[provider]?.[0]?.value ?? "";
                                      setField("llm_model", defaultModel);
                                    }}
                                  >
                                    <SelectTrigger>
                                      <SelectValue placeholder="Select LLM provider..." />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {LLM_PROVIDER_OPTIONS.map((p) => (
                                        <SelectItem key={p.value} value={p.value}>
                                          {p.label}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="space-y-2">
                                  <Label>Model</Label>
                                  <Select
                                    value={form.llm_model}
                                    onValueChange={(v) => setField("llm_model", v)}
                                  >
                                    <SelectTrigger>
                                      <SelectValue placeholder="Select model..." />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {(LLM_MODEL_OPTIONS[form.llm_provider] || []).map((m) => (
                                        <SelectItem key={m.value} value={m.value}>
                                          {m.label}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                              </div>
                            </Section>
                          </>
                        )}

                        <Separator />

                        <Section
                          title="AI Thinking"
                          description="Control whether the AI reasons deeply before responding. Turning this off reduces cost and latency."
                        >
                          <div className="flex items-center justify-between rounded-lg border p-3">
                            <div className="space-y-0.5">
                              <Label>Enable Thinking</Label>
                              <p className="text-xs text-muted-foreground">
                                Uses more tokens for deeper reasoning. Off is recommended for most voice bots.
                              </p>
                            </div>
                            <Switch
                              checked={form.llm_thinking_enabled}
                              onCheckedChange={(v) => setField("llm_thinking_enabled", v)}
                            />
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
                        description="Select which provider this bot uses for calls."
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
                                onClick={() => {
                                  setField("telephony_provider", p);
                                  setField("phone_number_id", null);
                                }}
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

                      </Section>

                      <Section
                        title="Phone Number"
                        description="Select which phone number this bot uses for outbound calls."
                      >
                        <Select
                          value={form.phone_number_id || "default"}
                          onValueChange={(v) =>
                            setField("phone_number_id", v === "default" ? null : v)
                          }
                        >
                          <SelectTrigger className="w-full max-w-md">
                            <SelectValue placeholder="Use default number" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="default">
                              Use default for provider
                            </SelectItem>
                            {(phoneNumbers || [])
                              .filter((pn) => pn.provider === form.telephony_provider)
                              .map((pn) => (
                                <SelectItem key={pn.id} value={pn.id}>
                                  {pn.phone_number}
                                  {pn.label ? ` — ${pn.label}` : ""}
                                  {pn.is_default ? " (default)" : ""}
                                </SelectItem>
                              ))}
                          </SelectContent>
                        </Select>

                        <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
                          <p className="text-xs text-muted-foreground">
                            Phone numbers and telephony credentials are managed in{" "}
                            <a href="/settings" className="text-violet-400 hover:underline">
                              Settings
                            </a>
                            .
                          </p>
                        </div>
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
                          description="CRM tagging and workflow triggers for this bot."
                        >
                          <div className="space-y-4">
                            <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
                              <p className="text-xs text-muted-foreground">
                                GHL API Key and Location ID are configured at the account level in{" "}
                                <a href="/settings" className="text-violet-400 hover:underline">
                                  Settings
                                </a>
                                .
                              </p>
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
                            <Webhook className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
                            <p className="text-sm text-muted-foreground">
                              No workflows configured yet.
                            </p>
                            <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
                              Add a workflow to trigger CRM automations based
                              on call events like confirmations, objections, or post-call tags.
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

                    {/* n8n Webhook Automations */}
                    <Card>
                      <CardContent className="pt-6 space-y-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <h3 className="text-sm font-semibold">n8n Webhook Automations</h3>
                            <p className="text-xs text-muted-foreground mt-0.5">
                              Trigger n8n workflows via webhooks at different call stages
                            </p>
                          </div>
                          <Button type="button" variant="outline" size="sm" onClick={addN8nAutomation}>
                            <Plus className="mr-1 h-3.5 w-3.5" /> Add Automation
                          </Button>
                        </div>

                        {form.n8n_automations.length === 0 && (
                          <div className="rounded-lg border border-dashed p-8 text-center">
                            <Webhook className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
                            <p className="text-sm text-muted-foreground">
                              No n8n automations configured.
                            </p>
                            <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
                              Add one to trigger webhooks on call events.
                            </p>
                          </div>
                        )}

                        {form.n8n_automations.map((automation) => (
                          <div key={automation.id} className="rounded-lg border p-4 space-y-3">
                            <div className="flex items-start gap-3">
                              <div className="flex-1 space-y-3">
                                <div className="grid grid-cols-2 gap-3">
                                  <div>
                                    <Label className="text-xs">Name</Label>
                                    <Input
                                      placeholder="Automation name"
                                      value={automation.name}
                                      onChange={(e) => updateN8nAutomation(automation.id, { name: e.target.value })}
                                      className="h-8 text-sm"
                                    />
                                  </div>
                                  <div>
                                    <Label className="text-xs">Webhook URL</Label>
                                    <Input
                                      placeholder="https://n8n.example.com/webhook/..."
                                      value={automation.webhook_url}
                                      onChange={(e) => updateN8nAutomation(automation.id, { webhook_url: e.target.value })}
                                      className="h-8 text-sm font-mono"
                                    />
                                  </div>
                                </div>

                                <div className="flex items-center gap-4">
                                  <div className="flex items-center gap-2">
                                    <Switch
                                      checked={automation.enabled}
                                      onCheckedChange={(checked) => updateN8nAutomation(automation.id, { enabled: checked })}
                                    />
                                    <span className="text-xs text-muted-foreground w-6">
                                      {automation.enabled ? "On" : "Off"}
                                    </span>
                                  </div>
                                  <div className="flex gap-1">
                                    {(["pre_call", "post_call"] as const).map((t) => (
                                      <Button
                                        key={t}
                                        type="button"
                                        size="sm"
                                        variant={automation.timing === t ? "default" : "outline"}
                                        onClick={() => updateN8nAutomation(automation.id, { timing: t })}
                                        className="h-7 text-xs px-3"
                                      >
                                        {t === "pre_call" ? "Pre-Call" : "Post-Call"}
                                      </Button>
                                    ))}
                                  </div>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8 shrink-0 ml-auto text-destructive"
                                    onClick={() => removeN8nAutomation(automation.id)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>

                                {/* Payload sections */}
                                <div>
                                  <Label className="text-xs">Payload Sections</Label>
                                  <div className="flex flex-wrap gap-2 mt-1">
                                    {["call", "analysis", "contact", "bot_config"].map((section) => (
                                      <label key={section} className="flex items-center gap-1 text-xs">
                                        <input
                                          type="checkbox"
                                          checked={automation.payload_sections.includes(section)}
                                          onChange={(e) => {
                                            const sections = e.target.checked
                                              ? [...automation.payload_sections, section]
                                              : automation.payload_sections.filter((s) => s !== section);
                                            updateN8nAutomation(automation.id, { payload_sections: sections });
                                          }}
                                        />
                                        {section === "bot_config" ? "Bot Config" : section.charAt(0).toUpperCase() + section.slice(1)}
                                      </label>
                                    ))}
                                    <label className="flex items-center gap-1 text-xs">
                                      <input
                                        type="checkbox"
                                        checked={automation.include_transcript}
                                        onChange={(e) => updateN8nAutomation(automation.id, { include_transcript: e.target.checked })}
                                      />
                                      Include Transcript
                                    </label>
                                  </div>
                                </div>

                                {/* Conditions (only for post_call) */}
                                {automation.timing === "post_call" && (
                                  <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                      <Label className="text-xs">Conditions</Label>
                                      <select
                                        className="text-xs border rounded px-1 py-0.5"
                                        value={automation.condition_logic}
                                        onChange={(e) => updateN8nAutomation(automation.id, { condition_logic: e.target.value as "all" | "any" })}
                                      >
                                        <option value="all">Match ALL</option>
                                        <option value="any">Match ANY</option>
                                      </select>
                                      <Button type="button" variant="outline" size="sm" className="text-xs ml-auto" onClick={() => addN8nCondition(automation.id)}>
                                        + Condition
                                      </Button>
                                    </div>
                                    {automation.conditions.length === 0 && (
                                      <p className="text-xs text-muted-foreground">No conditions — webhook fires on every post-call.</p>
                                    )}
                                    {automation.conditions.map((cond, idx) => (
                                      <div key={idx} className="flex items-center gap-2">
                                        <select
                                          className="text-xs border rounded px-2 py-1 flex-1"
                                          value={cond.field}
                                          onChange={(e) => updateN8nCondition(automation.id, idx, { field: e.target.value })}
                                        >
                                          <option value="goal_outcome">Goal Outcome</option>
                                          <option value="sentiment">Sentiment</option>
                                          <option value="lead_temperature">Lead Temperature</option>
                                          <option value="interest_level">Interest Level</option>
                                          <option value="outcome">Call Outcome</option>
                                        </select>
                                        <select
                                          className="text-xs border rounded px-2 py-1"
                                          value={cond.operator}
                                          onChange={(e) => updateN8nCondition(automation.id, idx, { operator: e.target.value as N8nCondition["operator"] })}
                                        >
                                          <option value="equals">equals</option>
                                          <option value="not_equals">not equals</option>
                                          <option value="in">in</option>
                                          <option value="not_in">not in</option>
                                          <option value="contains">contains</option>
                                          <option value="exists">exists</option>
                                        </select>
                                        {cond.operator !== "exists" && (
                                          <Input
                                            className="text-xs flex-1 h-8"
                                            placeholder="Value"
                                            value={typeof cond.value === "string" ? cond.value : Array.isArray(cond.value) ? cond.value.join(", ") : ""}
                                            onChange={(e) => {
                                              const val = cond.operator === "in" || cond.operator === "not_in"
                                                ? e.target.value.split(",").map((s) => s.trim())
                                                : e.target.value;
                                              updateN8nCondition(automation.id, idx, { value: val });
                                            }}
                                          />
                                        )}
                                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => removeN8nCondition(automation.id, idx)}>
                                          <Trash2 className="h-3 w-3" />
                                        </Button>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
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
                    TAB 5: Goals
                   ================================================================ */}
                <TabsContent value="goals">
                  <Card>
                    <CardContent className="pt-6 space-y-8">
                      {!goalConfig ? (
                        <div className="flex flex-col items-center justify-center py-16">
                          <div className="rounded-full bg-violet-500/10 p-4 mb-4">
                            <Target className="h-8 w-8 text-violet-400" />
                          </div>
                          <p className="text-base font-medium mb-1">No Goal Configuration</p>
                          <p className="text-sm text-muted-foreground mb-6 text-center max-w-md leading-relaxed">
                            Enable goal-based analytics to track call outcomes, detect red flags, and capture structured data from every conversation.
                          </p>
                          <Button onClick={initGoalConfig} className="gap-1.5">
                            <Plus className="h-4 w-4" />
                            Enable Goal Analytics
                          </Button>
                        </div>
                      ) : (
                        <>
                          {/* Goal Type & Description */}
                          <Section title="Goal Definition" description="Define what this bot is trying to achieve on each call.">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <Label>Goal Type</Label>
                                <Input
                                  placeholder="e.g., event_invitation, lead_qualification"
                                  value={goalConfig.goal_type}
                                  onChange={(e) => updateGoalField("goal_type", e.target.value)}
                                />
                              </div>
                            </div>
                            <div className="space-y-2">
                              <Label>Goal Description</Label>
                              <Textarea
                                placeholder="Describe the primary goal of each call..."
                                value={goalConfig.goal_description}
                                onChange={(e) => updateGoalField("goal_description", e.target.value)}
                                rows={2}
                              />
                            </div>
                          </Section>

                          <Separator />

                          {/* Success Criteria */}
                          <Section title="Success Criteria" description="Define possible outcomes. Exactly one must be marked as primary.">
                            <div className="space-y-3">
                              {goalConfig.success_criteria.length === 0 && (
                                <div className="rounded-lg border border-dashed p-6 text-center">
                                  <Check className="h-6 w-6 text-muted-foreground/30 mx-auto mb-2" />
                                  <p className="text-sm text-muted-foreground">No success criteria defined yet.</p>
                                  <p className="text-xs text-muted-foreground mt-1">Add criteria to track how calls are resolved.</p>
                                </div>
                              )}
                              {goalConfig.success_criteria.map((c, i) => (
                                <div key={i} className="flex items-center gap-3 rounded-lg border p-3">
                                  <div className="flex-1 grid grid-cols-2 gap-3">
                                    <Input
                                      placeholder="ID (e.g., confirmed)"
                                      value={c.id}
                                      onChange={(e) => updateCriterion(i, { id: e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") })}
                                    />
                                    <Input
                                      placeholder="Label (e.g., Confirmed attendance)"
                                      value={c.label}
                                      onChange={(e) => updateCriterion(i, { label: e.target.value })}
                                    />
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                                      <input
                                        type="radio"
                                        name="primary_criterion"
                                        checked={c.is_primary || false}
                                        onChange={() => updateCriterion(i, { is_primary: true })}
                                        className="accent-violet-500"
                                      />
                                      Primary
                                    </label>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                      onClick={() => removeCriterion(i)}
                                    >
                                      <X className="h-3.5 w-3.5" />
                                    </Button>
                                  </div>
                                </div>
                              ))}
                              <Button type="button" variant="outline" size="sm" onClick={addSuccessCriterion} className="gap-1.5">
                                <Plus className="h-3.5 w-3.5" />
                                Add Criterion
                              </Button>
                            </div>
                          </Section>

                          <Separator />

                          {/* Red Flags */}
                          <Section title="Red Flags" description="Define signals to watch for during or after calls. Critical and high severity flags trigger alerts.">
                            <div className="space-y-3">
                              {(goalConfig.red_flags || []).length === 0 && (
                                <div className="rounded-lg border border-dashed p-6 text-center">
                                  <AlertTriangle className="h-6 w-6 text-muted-foreground/30 mx-auto mb-2" />
                                  <p className="text-sm text-muted-foreground">No red flags configured.</p>
                                  <p className="text-xs text-muted-foreground mt-1">Add red flags to detect concerning signals like DND requests or legal threats.</p>
                                </div>
                              )}
                              {(goalConfig.red_flags || []).map((rf, i) => (
                                <div key={i} className="rounded-lg border p-3 space-y-3">
                                  <div className="flex items-center gap-3">
                                    <div className="flex-1 grid grid-cols-2 gap-3">
                                      <Input
                                        placeholder="ID (e.g., dnd_threat)"
                                        value={rf.id}
                                        onChange={(e) => updateRedFlag(i, { id: e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") })}
                                      />
                                      <Input
                                        placeholder="Label (e.g., DND / legal threat)"
                                        value={rf.label}
                                        onChange={(e) => updateRedFlag(i, { label: e.target.value })}
                                      />
                                    </div>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                      onClick={() => removeRedFlag(i)}
                                    >
                                      <X className="h-3.5 w-3.5" />
                                    </Button>
                                  </div>
                                  <div className="grid grid-cols-3 gap-3 items-center">
                                    <div className="flex items-center gap-2">
                                      <Select value={rf.severity} onValueChange={(v) => updateRedFlag(i, { severity: v as RedFlagConfig["severity"] })}>
                                        <SelectTrigger><SelectValue placeholder="Severity" /></SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="critical">Critical</SelectItem>
                                          <SelectItem value="high">High</SelectItem>
                                          <SelectItem value="medium">Medium</SelectItem>
                                          <SelectItem value="low">Low</SelectItem>
                                        </SelectContent>
                                      </Select>
                                      <Badge
                                        variant="outline"
                                        className={`text-[10px] shrink-0 capitalize ${SEVERITY_COLORS[rf.severity] || ""}`}
                                      >
                                        {rf.severity}
                                      </Badge>
                                    </div>
                                    <Select value={rf.detect_in || "post_call"} onValueChange={(v) => updateRedFlag(i, { detect_in: v as "realtime" | "post_call" })}>
                                      <SelectTrigger><SelectValue placeholder="Detection" /></SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="post_call">Post-Call (LLM)</SelectItem>
                                        <SelectItem value="realtime">Real-time (Keywords)</SelectItem>
                                      </SelectContent>
                                    </Select>
                                    {rf.detect_in === "realtime" && (
                                      <Input
                                        placeholder="Keywords (comma-separated)"
                                        value={(rf.keywords || []).join(", ")}
                                        onChange={(e) => updateRedFlag(i, { keywords: e.target.value.split(",").map((k) => k.trim()).filter(Boolean) })}
                                      />
                                    )}
                                  </div>
                                </div>
                              ))}
                              <Button type="button" variant="outline" size="sm" onClick={addRedFlag} className="gap-1.5">
                                <Plus className="h-3.5 w-3.5" />
                                Add Red Flag
                              </Button>
                            </div>
                          </Section>

                          <Separator />

                          {/* Data Capture Fields */}
                          <Section title="Data Capture Fields" description="Structured data to extract from each call transcript.">
                            <div className="space-y-3">
                              {(goalConfig.data_capture_fields || []).length === 0 && (
                                <div className="rounded-lg border border-dashed p-6 text-center">
                                  <Database className="h-6 w-6 text-muted-foreground/30 mx-auto mb-2" />
                                  <p className="text-sm text-muted-foreground">No capture fields defined.</p>
                                  <p className="text-xs text-muted-foreground mt-1">Add fields to extract structured data like dates, preferences, or decisions from transcripts.</p>
                                </div>
                              )}
                              {(goalConfig.data_capture_fields || []).map((f, i) => (
                                <div key={i} className="rounded-lg border p-3 space-y-3">
                                  <div className="flex items-start gap-3">
                                    <div className="flex-1 grid grid-cols-3 gap-3">
                                      <Input
                                        placeholder="ID (e.g., attending_date)"
                                        value={f.id}
                                        onChange={(e) => updateCaptureField(i, { id: e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") })}
                                      />
                                      <Input
                                        placeholder="Label"
                                        value={f.label}
                                        onChange={(e) => updateCaptureField(i, { label: e.target.value })}
                                      />
                                      <Select value={f.type} onValueChange={(v) => updateCaptureField(i, { type: v as DataCaptureField["type"], ...(v !== "enum" ? { enum_values: undefined } : {}) })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="string">String</SelectItem>
                                          <SelectItem value="integer">Integer</SelectItem>
                                          <SelectItem value="float">Float</SelectItem>
                                          <SelectItem value="boolean">Boolean</SelectItem>
                                          <SelectItem value="enum">Enum</SelectItem>
                                        </SelectContent>
                                      </Select>
                                    </div>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 text-muted-foreground hover:text-destructive mt-1"
                                      onClick={() => removeCaptureField(i)}
                                    >
                                      <X className="h-3.5 w-3.5" />
                                    </Button>
                                  </div>
                                  {f.type === "enum" && (
                                    <Input
                                      placeholder="Enum values (comma-separated, e.g., yes, no, maybe)"
                                      defaultValue={(f.enum_values || []).join(", ")}
                                      onBlur={(e) => updateCaptureField(i, { enum_values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })}
                                    />
                                  )}
                                </div>
                              ))}
                              <Button type="button" variant="outline" size="sm" onClick={addCaptureField} className="gap-1.5">
                                <Plus className="h-3.5 w-3.5" />
                                Add Capture Field
                              </Button>
                            </div>
                          </Section>

                          <Separator />

                          {/* Remove goal config */}
                          <div className="flex justify-end">
                            <Button
                              type="button"
                              variant="ghost"
                              className="text-destructive hover:text-destructive gap-1.5"
                              onClick={() => setGoalConfig(null)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Remove Goal Configuration
                            </Button>
                          </div>
                        </>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* ================================================================
                    TAB 6: Settings
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

                      <Separator />

                      <Section
                        title="Concurrency"
                        description="Maximum number of simultaneous active calls for this bot."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">
                              Max Concurrent Calls
                            </p>
                            <p className="text-xs text-muted-foreground">
                              Limits how many calls can run at the same time.
                              Lower this if you notice audio quality drops under load.
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <Input
                              type="number"
                              value={form.max_concurrent_calls}
                              onChange={(e) =>
                                setField(
                                  "max_concurrent_calls",
                                  Math.max(1, Math.min(50, parseInt(e.target.value) || 5)),
                                )
                              }
                              min={1}
                              max={50}
                              className="w-20 text-center"
                            />
                            <span className="text-sm text-muted-foreground">
                              calls
                            </span>
                          </div>
                        </div>
                      </Section>

                      <Separator />

                      <Section
                        title="Circuit Breaker"
                        description="Automatically pause queued calls when consecutive failures are detected."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">
                              Circuit Breaker
                            </p>
                            <p className="text-xs text-muted-foreground">
                              When disabled, failures won&apos;t trip the circuit
                              breaker and calls will keep flowing regardless of
                              errors.
                            </p>
                          </div>
                          <Switch
                            checked={form.circuit_breaker_enabled}
                            onCheckedChange={(v) =>
                              setField("circuit_breaker_enabled", v)
                            }
                          />
                        </div>

                        {form.circuit_breaker_enabled && (
                          <div className="flex items-center justify-between rounded-lg border p-4">
                            <div className="space-y-1">
                              <p className="text-sm font-medium">
                                Failure Threshold
                              </p>
                              <p className="text-xs text-muted-foreground">
                                Number of consecutive failures before the circuit
                                breaker trips and holds queued calls.
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Input
                                type="number"
                                value={form.circuit_breaker_threshold}
                                onChange={(e) =>
                                  setField(
                                    "circuit_breaker_threshold",
                                    Math.max(1, Math.min(50, parseInt(e.target.value) || 1)),
                                  )
                                }
                                min={1}
                                max={50}
                                className="w-20 text-center"
                              />
                              <span className="text-sm text-muted-foreground">
                                failures
                              </span>
                            </div>
                          </div>
                        )}
                      </Section>

                      <Separator />

                      <Section
                        title="Background Office Noise"
                        description="Add subtle office ambience to calls for a more natural, human-like experience."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">
                              Office Background Noise
                            </p>
                            <p className="text-xs text-muted-foreground">
                              Plays subtle office ambience (keyboard sounds, distant
                              murmur, air conditioning) throughout the call. Disable
                              if callers report audio issues.
                            </p>
                          </div>
                          <Switch
                            checked={form.ambient_sound_enabled}
                            onCheckedChange={(v) =>
                              setField("ambient_sound_enabled", v)
                            }
                          />
                        </div>
                      </Section>

                      <Separator />

                      <Section
                        title="Call Memory"
                        description="Inject previous call summaries into the AI prompt so it remembers past conversations."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">Call Memory</p>
                            <p className="text-xs text-muted-foreground">
                              When enabled, the AI will see summaries of previous calls
                              with the same contact and can reference them naturally.
                            </p>
                          </div>
                          <Switch
                            checked={form.call_memory_enabled}
                            onCheckedChange={(v) => setField("call_memory_enabled", v)}
                          />
                        </div>

                        {form.call_memory_enabled && (
                          <div className="flex items-center justify-between rounded-lg border p-4">
                            <div className="space-y-1">
                              <p className="text-sm font-medium">Memory Depth</p>
                              <p className="text-xs text-muted-foreground">
                                Number of past calls to include in the AI&apos;s memory.
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Input
                                type="number"
                                value={form.call_memory_count}
                                onChange={(e) =>
                                  setField("call_memory_count", Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))
                                }
                                min={1}
                                max={10}
                                className="w-20 text-center"
                              />
                              <span className="text-sm text-muted-foreground">calls</span>
                            </div>
                          </div>
                        )}
                      </Section>

                      <Separator />

                      <Section
                        title="Post-Call Sequence"
                        description="Automatically run an engagement sequence after calls complete."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">Sequence Template</p>
                            <p className="text-xs text-muted-foreground">
                              Select a sequence to trigger after this bot finishes a call.
                            </p>
                          </div>
                          <Select
                            value={form.sequence_template_id || "none"}
                            onValueChange={(v) => setField("sequence_template_id", v === "none" ? null : v)}
                          >
                            <SelectTrigger className="w-64">
                              <SelectValue placeholder="No sequence" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">No sequence</SelectItem>
                              {sequenceTemplates.map((t) => (
                                <SelectItem key={t.id} value={t.id}>
                                  {t.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </Section>

                      <Separator />

                      <Section
                        title="Scheduled Callbacks"
                        description="Allow the AI to schedule callback calls when the contact is busy or requests a later call."
                      >
                        <div className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-1">
                            <p className="text-sm font-medium">Enable Callbacks</p>
                            <p className="text-xs text-muted-foreground">
                              The AI can schedule a callback when the person says
                              &quot;call me later&quot; or is busy.
                            </p>
                          </div>
                          <Switch
                            checked={form.callback_enabled}
                            onCheckedChange={(v) => setField("callback_enabled", v)}
                          />
                        </div>

                        {form.callback_enabled && (
                          <div className="space-y-4">
                            {/* Template Picker */}
                            <div>
                              <Label className="text-sm font-medium">Retry Schedule Template</Label>
                              <div className="flex gap-2 mt-2">
                                {Object.entries(RETRY_TEMPLATES).map(([key, tmpl]) => (
                                  <Button
                                    key={key}
                                    variant={form.callback_schedule?.template === key ? "default" : "outline"}
                                    size="sm"
                                    onClick={() => setField("callback_schedule", {
                                      template: key as CallbackSchedule["template"],
                                      steps: tmpl.steps,
                                    })}
                                  >
                                    {tmpl.label}
                                  </Button>
                                ))}
                                {form.callback_schedule?.template === "custom" && (
                                  <Badge variant="secondary">Custom</Badge>
                                )}
                              </div>
                            </div>

                            {/* Step List */}
                            {form.callback_schedule && form.callback_schedule.steps.length > 0 && (
                              <div className="space-y-2">
                                <Label className="text-sm font-medium">Retry Steps</Label>
                                {form.callback_schedule.steps.map((step, idx) => (
                                  <div key={idx} className="flex items-center gap-2 p-2 rounded border bg-muted/30">
                                    <Badge variant="outline" className="shrink-0">Step {idx + 1}</Badge>

                                    <Select
                                      value={step.delay_type ? "next_day" : "delay"}
                                      onValueChange={(val) => {
                                        const newSteps = [...form.callback_schedule!.steps];
                                        if (val === "next_day") {
                                          newSteps[idx] = { delay_type: "next_day", preferred_window: step.preferred_window };
                                        } else {
                                          newSteps[idx] = { delay_hours: step.delay_hours || 3, preferred_window: step.preferred_window };
                                        }
                                        setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                      }}
                                    >
                                      <SelectTrigger className="w-[140px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="delay">After X hours</SelectItem>
                                        <SelectItem value="next_day">Next day</SelectItem>
                                      </SelectContent>
                                    </Select>

                                    {!step.delay_type && (
                                      <Input
                                        type="number"
                                        min={0.5}
                                        max={48}
                                        step={0.5}
                                        value={step.delay_hours || 3}
                                        onChange={(e) => {
                                          const newSteps = [...form.callback_schedule!.steps];
                                          newSteps[idx] = { ...newSteps[idx], delay_hours: parseFloat(e.target.value) || 3 };
                                          delete (newSteps[idx] as any).delay_type;
                                          setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                        }}
                                        className="w-[80px]"
                                      />
                                    )}

                                    {/* Preferred Window */}
                                    <div className="flex items-center gap-1 ml-2">
                                      <Switch
                                        checked={!!step.preferred_window}
                                        onCheckedChange={(checked) => {
                                          const newSteps = [...form.callback_schedule!.steps];
                                          if (checked) {
                                            newSteps[idx] = { ...newSteps[idx], preferred_window: [11, 13] };
                                          } else {
                                            const { preferred_window, ...rest } = newSteps[idx];
                                            newSteps[idx] = rest;
                                          }
                                          setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                        }}
                                      />
                                      <span className="text-xs text-muted-foreground">Window</span>
                                    </div>

                                    {step.preferred_window && (
                                      <>
                                        <Input
                                          type="number"
                                          min={0}
                                          max={23}
                                          value={step.preferred_window[0]}
                                          onChange={(e) => {
                                            const newSteps = [...form.callback_schedule!.steps];
                                            newSteps[idx] = {
                                              ...newSteps[idx],
                                              preferred_window: [parseInt(e.target.value) || 0, step.preferred_window![1]],
                                            };
                                            setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                          }}
                                          className="w-[60px]"
                                        />
                                        <span className="text-muted-foreground">to</span>
                                        <Input
                                          type="number"
                                          min={1}
                                          max={23}
                                          value={step.preferred_window[1]}
                                          onChange={(e) => {
                                            const newSteps = [...form.callback_schedule!.steps];
                                            newSteps[idx] = {
                                              ...newSteps[idx],
                                              preferred_window: [step.preferred_window![0], parseInt(e.target.value) || 23],
                                            };
                                            setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                          }}
                                          className="w-[60px]"
                                        />
                                      </>
                                    )}

                                    {/* Delete step */}
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="ml-auto text-destructive"
                                      onClick={() => {
                                        const newSteps = form.callback_schedule!.steps.filter((_, i) => i !== idx);
                                        if (newSteps.length > 0) {
                                          setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                        } else {
                                          setField("callback_schedule", null);
                                        }
                                      }}
                                    >
                                      X
                                    </Button>
                                  </div>
                                ))}

                                {/* Add step button */}
                                {form.callback_schedule.steps.length < 10 && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                      const newSteps = [...form.callback_schedule!.steps, { delay_hours: 3 }];
                                      setField("callback_schedule", { ...form.callback_schedule!, template: "custom", steps: newSteps });
                                    }}
                                  >
                                    + Add Step
                                  </Button>
                                )}
                              </div>
                            )}

                            {/* Initialize schedule if enabled but no schedule yet */}
                            {!form.callback_schedule && (
                              <div className="text-center py-4">
                                <p className="text-sm text-muted-foreground mb-2">No retry schedule configured</p>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setField("callback_schedule", {
                                    template: "standard",
                                    steps: RETRY_TEMPLATES.standard.steps,
                                  })}
                                >
                                  Set up retry schedule
                                </Button>
                              </div>
                            )}

                            <div className="flex items-center justify-between rounded-lg border p-4">
                              <div className="space-y-1">
                                <p className="text-sm font-medium">Timezone</p>
                                <p className="text-xs text-muted-foreground">
                                  Timezone for interpreting callback times and calling window.
                                </p>
                              </div>
                              <Select
                                value={form.callback_timezone}
                                onValueChange={(v) => setField("callback_timezone", v)}
                              >
                                <SelectTrigger className="w-48">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="Asia/Kolkata">Asia/Kolkata (IST)</SelectItem>
                                  <SelectItem value="America/New_York">America/New_York (EST)</SelectItem>
                                  <SelectItem value="America/Los_Angeles">America/Los_Angeles (PST)</SelectItem>
                                  <SelectItem value="America/Chicago">America/Chicago (CST)</SelectItem>
                                  <SelectItem value="Europe/London">Europe/London (GMT)</SelectItem>
                                  <SelectItem value="Europe/Berlin">Europe/Berlin (CET)</SelectItem>
                                  <SelectItem value="Asia/Dubai">Asia/Dubai (GST)</SelectItem>
                                  <SelectItem value="Asia/Singapore">Asia/Singapore (SGT)</SelectItem>
                                  <SelectItem value="Australia/Sydney">Australia/Sydney (AEST)</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>

                            <div className="flex items-center justify-between rounded-lg border p-4">
                              <div className="space-y-1">
                                <p className="text-sm font-medium">Calling Window</p>
                                <p className="text-xs text-muted-foreground">
                                  Only place callbacks during these hours (in the bot&apos;s timezone).
                                </p>
                              </div>
                              <div className="flex items-center gap-2">
                                <Input
                                  type="number"
                                  value={form.callback_window_start}
                                  onChange={(e) =>
                                    setField("callback_window_start", Math.max(0, Math.min(23, parseInt(e.target.value) || 9)))
                                  }
                                  min={0}
                                  max={23}
                                  className="w-16 text-center"
                                />
                                <span className="text-sm text-muted-foreground">to</span>
                                <Input
                                  type="number"
                                  value={form.callback_window_end}
                                  onChange={(e) =>
                                    setField("callback_window_end", Math.max(1, Math.min(24, parseInt(e.target.value) || 20)))
                                  }
                                  min={1}
                                  max={24}
                                  className="w-16 text-center"
                                />
                                <span className="text-sm text-muted-foreground">hrs</span>
                              </div>
                            </div>
                          </div>
                        )}
                      </Section>

                      <Separator />

                      <Section
                        title="Bot Switching"
                        description="Configure target bots that the AI can transfer calls to (e.g., for language switching)."
                      >
                        {form.bot_switch_targets.map((target) => (
                          <div
                            key={target.id}
                            className="rounded-lg border p-4 space-y-3"
                          >
                            <div className="flex items-center justify-between">
                              <p className="text-sm font-medium">Switch Target</p>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-red-400"
                                onClick={() => removeSwitchTarget(target.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="space-y-1.5">
                                <Label className="text-xs">Target Bot</Label>
                                <Select
                                  value={target.target_bot_id}
                                  onValueChange={(v) =>
                                    updateSwitchTarget(target.id, { target_bot_id: v })
                                  }
                                >
                                  <SelectTrigger>
                                    <SelectValue placeholder="Select a bot..." />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(allBots || [])
                                      .filter((b) => b.id !== botId && b.is_active)
                                      .map((b) => (
                                        <SelectItem key={b.id} value={b.id}>
                                          {b.agent_name} — {b.company_name}
                                        </SelectItem>
                                      ))}
                                  </SelectContent>
                                </Select>
                              </div>
                              <div className="space-y-1.5">
                                <Label className="text-xs">AI Trigger Description</Label>
                                <Input
                                  placeholder="e.g. Customer prefers Hindi"
                                  value={target.description}
                                  onChange={(e) =>
                                    updateSwitchTarget(target.id, {
                                      description: e.target.value,
                                    })
                                  }
                                />
                              </div>
                            </div>
                          </div>
                        ))}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={addSwitchTarget}
                          className="gap-1"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Add Switch Target
                        </Button>
                      </Section>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          </ScrollArea>

          {/* Sticky footer save bar with unsaved changes indicator */}
          <div className={`border-t px-6 py-3 flex items-center justify-between transition-colors ${
            hasUnsavedChanges
              ? "border-amber-500/40 bg-amber-500/5 backdrop-blur-md"
              : "border-border/50 bg-background/80 backdrop-blur-md"
          }`}>
            <div className="flex items-center gap-2">
              {hasUnsavedChanges ? (
                <>
                  <div className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
                  <p className="text-xs font-medium text-amber-300">
                    Unsaved changes
                  </p>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {isNew
                    ? "Fill in the required fields and save to create your bot."
                    : "All changes saved."}
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              {hasUnsavedChanges && !isNew && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={discardChanges}
                  className="gap-1.5 text-muted-foreground"
                >
                  <Undo2 className="h-3.5 w-3.5" />
                  Discard
                </Button>
              )}
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
