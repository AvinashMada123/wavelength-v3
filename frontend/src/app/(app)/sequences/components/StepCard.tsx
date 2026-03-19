"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  ChevronDown,
  ChevronUp,
  Trash2,
  MessageSquare,
  Phone,
  Mail,
  Clock,
  Sparkles,
  FileText,
  ToggleLeft,
  Send,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { testStep } from "@/lib/sequences-api";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SequenceStep } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHANNEL_OPTIONS = [
  { value: "whatsapp_template", label: "WhatsApp Template", icon: MessageSquare },
  { value: "whatsapp_session", label: "WhatsApp Session", icon: MessageSquare },
  { value: "voice_call", label: "Voice Call", icon: Phone },
  { value: "sms", label: "SMS", icon: Mail },
];

const CONTENT_TYPE_OPTIONS = [
  { value: "static_template", label: "Static Template" },
  { value: "ai_generated", label: "AI Generated" },
  { value: "voice_call", label: "Voice Call" },
];

const TIMING_TYPE_OPTIONS = [
  { value: "delay", label: "Delay After Previous" },
  { value: "relative_to_event", label: "Relative to Event" },
  { value: "relative_to_signup", label: "After Signup/Call" },
  { value: "fixed_time", label: "Fixed Time" },
  { value: "immediate", label: "Immediate" },
];

const AI_MODEL_OPTIONS = [
  { value: "claude-sonnet", label: "Claude Sonnet" },
  { value: "claude-haiku", label: "Claude Haiku" },
];

function channelBadge(channel: string) {
  const opt = CHANNEL_OPTIONS.find((o) => o.value === channel);
  if (!opt) return channel;
  const Icon = opt.icon;
  return (
    <Badge variant="outline" className="gap-1 text-xs">
      <Icon className="h-3 w-3" />
      {opt.label}
    </Badge>
  );
}

function timingSummary(step: SequenceStep): string {
  if (step.timing_type === "immediate") return "Immediately";
  if (step.timing_type === "delay") {
    const val = step.timing_value as Record<string, number | string>;
    const hours = val?.hours ?? 0;
    const days = val?.days ?? 0;
    const parts: string[] = [];
    if (days) parts.push(`${days}d`);
    if (hours) parts.push(`${hours}h`);
    const time = val?.at_time;
    if (time) parts.push(`at ${time}`);
    return parts.length ? parts.join(" ") + " after prev" : "After previous";
  }
  if (step.timing_type === "relative_to_event") {
    const val = step.timing_value as Record<string, number | string>;
    const days = Number(val?.days ?? 0);
    const time = val?.time;
    const varName = val?.event_variable || "event_date";
    if (days < 0) {
      return `${Math.abs(days)}d before ${varName}${time ? ` at ${time}` : ""}`;
    } else if (days === 0) {
      return `${varName} day${time ? ` at ${time}` : ""}`;
    }
    return `${days}d after ${varName}${time ? ` at ${time}` : ""}`;
  }
  if (step.timing_type === "relative_to_signup") {
    const val = step.timing_value as Record<string, number | string>;
    const hours = val?.hours ?? 0;
    const days = val?.days ?? 0;
    const parts: string[] = [];
    if (days) parts.push(`${days}d`);
    if (hours) parts.push(`${hours}h`);
    const time = val?.time;
    if (time) parts.push(`at ${time}`);
    return parts.length ? parts.join(" ") + " after signup" : "After signup";
  }
  if (step.timing_type === "fixed_time") {
    const val = step.timing_value as Record<string, string>;
    return val?.time ? `At ${val.time}` : "Fixed time";
  }
  return step.timing_type;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface StepCardProps {
  step: SequenceStep;
  bots: { id: string; name: string }[];
  variables: Array<{ key: string; default_value: string; description: string; type?: string }>;
  onUpdate: (stepId: string, data: Partial<SequenceStep>) => void;
  onDelete: (stepId: string) => void;
  onTestPrompt: (prompt: string, model: string) => void;
  onAddVariable: (variable: { key: string; default_value: string; description: string; type: string }) => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StepCard({
  step,
  bots,
  variables,
  onUpdate,
  onDelete,
  onTestPrompt,
  onAddVariable,
  isExpanded,
  onToggleExpand,
}: StepCardProps) {
  // -- Debounced auto-save helpers --
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<Partial<SequenceStep>>({});

  const flush = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const data = pendingRef.current;
    if (Object.keys(data).length > 0) {
      onUpdate(step.id, data);
      pendingRef.current = {};
    }
  }, [onUpdate, step.id]);

  const queueSave = useCallback(
    (patch: Partial<SequenceStep>) => {
      pendingRef.current = { ...pendingRef.current, ...patch };
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(flush, 500);
    },
    [flush],
  );

  // Flush on unmount
  useEffect(() => () => flush(), [flush]);

  // Local state mirrors for controlled inputs
  const [name, setName] = useState(step.name);
  const [channel, setChannel] = useState(step.channel);
  const [contentType, setContentType] = useState(step.content_type);
  const [timingType, setTimingType] = useState(step.timing_type);
  const [timingValue, setTimingValue] = useState<Record<string, any>>(
    (step.timing_value as Record<string, any>) ?? {},
  );
  const [skipEnabled, setSkipEnabled] = useState(!!step.skip_conditions);
  const [skipField, setSkipField] = useState(
    (step.skip_conditions as Record<string, string>)?.field ?? "",
  );
  const [skipEquals, setSkipEquals] = useState(
    (step.skip_conditions as Record<string, string>)?.equals ?? "",
  );
  const [templateName, setTemplateName] = useState(step.whatsapp_template_name ?? "");
  const [templateParams, setTemplateParams] = useState(
    step.whatsapp_template_params ? JSON.stringify(step.whatsapp_template_params, null, 2) : "",
  );
  const [aiPrompt, setAiPrompt] = useState(step.ai_prompt ?? "");
  const [aiModel, setAiModel] = useState(step.ai_model ?? "claude-sonnet");
  const [voiceBotId, setVoiceBotId] = useState(step.voice_bot_id ?? "");
  const [expectsReply, setExpectsReply] = useState(step.expects_reply);
  const [replyPrompt, setReplyPrompt] = useState(
    (step.reply_handler as Record<string, string>)?.ai_prompt ?? "",
  );
  const [replySaveField, setReplySaveField] = useState(
    (step.reply_handler as Record<string, string>)?.save_field ?? "",
  );
  const [isActive, setIsActive] = useState(step.is_active);

  // Sync from props when step changes externally
  useEffect(() => {
    setName(step.name);
    setChannel(step.channel);
    setContentType(step.content_type);
    setTimingType(step.timing_type);
    setTimingValue((step.timing_value as Record<string, any>) ?? {});
    setIsActive(step.is_active);
  }, [step.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // -- Helpers to update + queue --
  function updateField(patch: Partial<SequenceStep>) {
    queueSave(patch);
  }

  // -----------------------------------------------------------------------
  // Collapsed view
  // -----------------------------------------------------------------------
  if (!isExpanded) {
    return (
      <Card
        className="cursor-pointer transition-colors hover:bg-muted/50"
        onClick={onToggleExpand}
      >
        <CardContent className="flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-100 text-xs font-semibold text-violet-700 dark:bg-violet-900/40 dark:text-violet-300">
              {step.step_order}
            </span>
            <div>
              <p className="text-sm font-medium">{step.name || "Untitled Step"}</p>
              <p className="text-xs text-muted-foreground">{timingSummary(step)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {channelBadge(channel)}
            {!isActive && (
              <Badge variant="secondary" className="text-xs">
                Inactive
              </Badge>
            )}
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  // -----------------------------------------------------------------------
  // Expanded view
  // -----------------------------------------------------------------------
  return (
    <Card className="border-violet-200 dark:border-violet-800">
      <CardContent className="space-y-5 p-5">
        {/* Header row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-100 text-xs font-semibold text-violet-700 dark:bg-violet-900/40 dark:text-violet-300">
              {step.step_order}
            </span>
            <span className="text-sm font-semibold">Step {step.step_order}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={onToggleExpand}
          >
            <ChevronUp className="h-4 w-4" />
          </Button>
        </div>

        {/* Name */}
        <div className="space-y-1.5">
          <Label className="text-xs">Step Name</Label>
          <Input
            value={name}
            placeholder="e.g. Follow-up WhatsApp"
            onChange={(e) => {
              setName(e.target.value);
              updateField({ name: e.target.value });
            }}
            onBlur={flush}
          />
        </div>

        {/* Channel + Content Type */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs">Channel</Label>
            <Select
              value={channel}
              onValueChange={(val) => {
                setChannel(val);
                onUpdate(step.id, { channel: val });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CHANNEL_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">Content Type</Label>
            <Select
              value={contentType}
              onValueChange={(val) => {
                setContentType(val);
                onUpdate(step.id, { content_type: val });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONTENT_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Timing */}
        <div className="space-y-1.5">
          <Label className="text-xs flex items-center gap-1">
            <Clock className="h-3 w-3" /> Timing
          </Label>
          <div className="grid gap-3 sm:grid-cols-3">
            <Select
              value={timingType}
              onValueChange={(val) => {
                setTimingType(val);
                let newTv = val === "immediate" ? {} : timingValue;
                if (val === "relative_to_event") {
                  const dtVars = variables.filter((v) => v.type === "datetime");
                  if (dtVars.length === 0) {
                    onAddVariable({
                      key: "event_date",
                      type: "datetime",
                      default_value: "",
                      description: "Event date and time",
                    });
                  }
                  const selectedVar = dtVars.length > 0 ? dtVars[0].key : "event_date";
                  newTv = { ...newTv, event_variable: selectedVar };
                }
                setTimingValue(newTv);
                onUpdate(step.id, { timing_type: val, timing_value: newTv });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMING_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {(timingType === "delay" || timingType === "relative_to_signup") && (
              <>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    placeholder="Days"
                    value={timingValue.days ?? ""}
                    onChange={(e) => {
                      const tv = { ...timingValue, days: Number(e.target.value) || 0 };
                      setTimingValue(tv);
                      updateField({ timing_value: tv });
                    }}
                    onBlur={flush}
                    className="w-full"
                  />
                  <span className="text-xs text-muted-foreground whitespace-nowrap">days</span>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    max={23}
                    placeholder="Hours"
                    value={timingValue.hours ?? ""}
                    onChange={(e) => {
                      const tv = { ...timingValue, hours: Number(e.target.value) || 0 };
                      setTimingValue(tv);
                      updateField({ timing_value: tv });
                    }}
                    onBlur={flush}
                    className="w-full"
                  />
                  <span className="text-xs text-muted-foreground whitespace-nowrap">hrs</span>
                </div>
              </>
            )}

            {timingType === "relative_to_event" && (
              <>
                <Select
                  value={timingValue.event_variable || "event_date"}
                  onValueChange={(val) => {
                    const tv = { ...timingValue, event_variable: val };
                    setTimingValue(tv);
                    updateField({ timing_value: tv });
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select variable" />
                  </SelectTrigger>
                  <SelectContent>
                    {variables
                      .filter((v) => v.type === "datetime")
                      .map((v) => (
                        <SelectItem key={v.key} value={v.key}>
                          {v.key}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    placeholder="Days"
                    value={timingValue.days ?? ""}
                    onChange={(e) => {
                      const tv = { ...timingValue, days: Number(e.target.value) };
                      setTimingValue(tv);
                      updateField({ timing_value: tv });
                    }}
                    onBlur={flush}
                    className="w-full"
                  />
                  <span className="text-xs text-muted-foreground whitespace-nowrap">days (- = before)</span>
                </div>
              </>
            )}

            {(timingType === "delay" || timingType === "fixed_time" || timingType === "relative_to_event" || timingType === "relative_to_signup") && (
              <Input
                type="time"
                value={timingValue.at_time ?? timingValue.time ?? ""}
                onChange={(e) => {
                  const tv = { ...timingValue, time: e.target.value };
                  setTimingValue(tv);
                  updateField({ timing_value: tv });
                }}
                onBlur={flush}
                className="w-full"
              />
            )}
          </div>
        </div>

        {/* Skip conditions */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs flex items-center gap-1">
              <ToggleLeft className="h-3 w-3" /> Skip Conditions
            </Label>
            <Switch
              checked={skipEnabled}
              onCheckedChange={(checked) => {
                setSkipEnabled(checked);
                onUpdate(step.id, {
                  skip_conditions: checked
                    ? { field: skipField, equals: skipEquals }
                    : null,
                });
              }}
            />
          </div>
          {skipEnabled && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">Field</Label>
                <Input
                  placeholder="e.g. lead.status"
                  value={skipField}
                  onChange={(e) => {
                    setSkipField(e.target.value);
                    updateField({
                      skip_conditions: { field: e.target.value, equals: skipEquals },
                    });
                  }}
                  onBlur={flush}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">Equals</Label>
                <Input
                  placeholder="e.g. converted"
                  value={skipEquals}
                  onChange={(e) => {
                    setSkipEquals(e.target.value);
                    updateField({
                      skip_conditions: { field: skipField, equals: e.target.value },
                    });
                  }}
                  onBlur={flush}
                />
              </div>
            </div>
          )}
        </div>

        {/* Conditional content */}
        {contentType === "static_template" && (
          <div className="space-y-3 rounded-lg border p-4">
            <Label className="text-xs flex items-center gap-1">
              <FileText className="h-3 w-3" /> WhatsApp Template
            </Label>
            <Input
              placeholder="Template name"
              value={templateName}
              onChange={(e) => {
                setTemplateName(e.target.value);
                updateField({ whatsapp_template_name: e.target.value });
              }}
              onBlur={flush}
            />
            <div className="space-y-1">
              <Label className="text-[10px] text-muted-foreground">
                Template Params (JSON array)
              </Label>
              <Textarea
                rows={3}
                className="font-mono text-xs"
                placeholder='["{{name}}", "{{date}}"]'
                value={templateParams}
                onChange={(e) => {
                  setTemplateParams(e.target.value);
                  try {
                    const parsed = JSON.parse(e.target.value);
                    updateField({ whatsapp_template_params: parsed });
                  } catch {
                    // wait for valid JSON
                  }
                }}
                onBlur={flush}
              />
            </div>
          </div>
        )}

        {contentType === "ai_generated" && (
          <div className="space-y-3 rounded-lg border p-4">
            <Label className="text-xs flex items-center gap-1">
              <Sparkles className="h-3 w-3" /> AI Content Generation
            </Label>
            <Textarea
              rows={5}
              placeholder="Write a follow-up message for {{lead_name}} about {{topic}}..."
              value={aiPrompt}
              onChange={(e) => {
                setAiPrompt(e.target.value);
                updateField({ ai_prompt: e.target.value });
              }}
              onBlur={flush}
            />
            <div className="flex items-center gap-3">
              <Select
                value={aiModel}
                onValueChange={(val) => {
                  setAiModel(val);
                  onUpdate(step.id, { ai_model: val });
                }}
              >
                <SelectTrigger className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AI_MODEL_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onTestPrompt(aiPrompt, aiModel)}
                disabled={!aiPrompt.trim()}
              >
                <Sparkles className="mr-1 h-3 w-3" />
                Test Prompt
              </Button>
            </div>
          </div>
        )}

        {contentType === "voice_call" && (
          <div className="space-y-3 rounded-lg border p-4">
            <Label className="text-xs flex items-center gap-1">
              <Phone className="h-3 w-3" /> Voice Bot
            </Label>
            <Select
              value={voiceBotId}
              onValueChange={(val) => {
                setVoiceBotId(val);
                onUpdate(step.id, { voice_bot_id: val });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a bot..." />
              </SelectTrigger>
              <SelectContent>
                {bots.map((b) => (
                  <SelectItem key={b.id} value={b.id}>
                    {b.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Reply handler */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs flex items-center gap-1">
              <MessageSquare className="h-3 w-3" /> Reply Handler
            </Label>
            <Switch
              checked={expectsReply}
              onCheckedChange={(checked) => {
                setExpectsReply(checked);
                onUpdate(step.id, {
                  expects_reply: checked,
                  reply_handler: checked
                    ? { ai_prompt: replyPrompt, save_field: replySaveField }
                    : null,
                });
              }}
            />
          </div>
          {expectsReply && (
            <div className="space-y-3">
              <Textarea
                rows={3}
                placeholder="AI prompt to handle the reply..."
                value={replyPrompt}
                onChange={(e) => {
                  setReplyPrompt(e.target.value);
                  updateField({
                    reply_handler: { ai_prompt: e.target.value, save_field: replySaveField },
                  });
                }}
                onBlur={flush}
              />
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">Save reply to field</Label>
                <Input
                  placeholder="e.g. lead.feedback"
                  value={replySaveField}
                  onChange={(e) => {
                    setReplySaveField(e.target.value);
                    updateField({
                      reply_handler: { ai_prompt: replyPrompt, save_field: e.target.value },
                    });
                  }}
                  onBlur={flush}
                />
              </div>
            </div>
          )}
        </div>

        {/* Send Test */}
        {(step.channel === "whatsapp_template" || step.channel === "whatsapp_session") && (
          <div className="flex items-center gap-2 border-t pt-4">
            <Input
              className="h-8 text-xs max-w-[200px]"
              placeholder="Phone e.g. +919609775259"
              id={`test-phone-${step.id}`}
            />
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs gap-1 shrink-0"
              onClick={async () => {
                const phoneInput = document.getElementById(`test-phone-${step.id}`) as HTMLInputElement;
                const phone = phoneInput?.value?.trim();
                if (!phone) { toast.error("Enter a phone number"); return; }
                phoneInput.disabled = true;
                const btn = phoneInput.nextElementSibling as HTMLButtonElement;
                if (btn) btn.disabled = true;
                try {
                  const result = await testStep(step.id, phone);
                  if (result.success) {
                    toast.success(`Test sent! Message ID: ${result.message_id || "OK"}`);
                  } else {
                    toast.error(result.error || "Test failed");
                  }
                } catch (err: any) {
                  toast.error(err?.message || "Test failed");
                } finally {
                  phoneInput.disabled = false;
                  if (btn) btn.disabled = false;
                }
              }}
            >
              <Send className="h-3 w-3" />
              Send Test
            </Button>
          </div>
        )}

        {/* Footer: Active toggle + Delete */}
        <div className="flex items-center justify-between border-t pt-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={isActive}
              onCheckedChange={(checked) => {
                setIsActive(checked);
                onUpdate(step.id, { is_active: checked });
              }}
            />
            <Label className="text-xs text-muted-foreground">Active</Label>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => onDelete(step.id)}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            Delete Step
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
