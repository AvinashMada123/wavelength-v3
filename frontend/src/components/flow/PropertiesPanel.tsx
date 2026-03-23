// frontend/src/components/flow/PropertiesPanel.tsx
"use client";

import { useCallback } from "react";
import type { Node } from "@xyflow/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { FlowNodeType } from "@/lib/flow-types";

interface PropertiesPanelProps {
  node: Node | null;
  onClose: () => void;
  onUpdateNode: (nodeId: string, updates: Partial<Node["data"]>) => void;
  bots: Array<{ id: string; name: string }>;
  className?: string;
}

export function PropertiesPanel({
  node,
  onClose,
  onUpdateNode,
  bots,
  className,
}: PropertiesPanelProps) {
  const updateConfig = useCallback(
    (key: string, value: any) => {
      if (!node) return;
      const newConfig = { ...(node.data.config as Record<string, any>), [key]: value };
      onUpdateNode(node.id, { config: newConfig });
    },
    [node, onUpdateNode],
  );

  const updateNestedConfig = useCallback(
    (parentKey: string, key: string, value: any) => {
      if (!node) return;
      const config = node.data.config as Record<string, any>;
      const newParent = { ...(config[parentKey] || {}), [key]: value };
      const newConfig = { ...config, [parentKey]: newParent };
      onUpdateNode(node.id, { config: newConfig });
    },
    [node, onUpdateNode],
  );

  if (!node) return null;

  const nodeType = node.data.nodeType as FlowNodeType;
  const config = node.data.config as Record<string, any>;

  return (
    <div className={cn("flex w-80 flex-col border-l bg-background", className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold">Properties</h3>
          <p className="text-xs text-muted-foreground capitalize">{nodeType.replace("_", " ")}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          {/* Node name — shared across all types */}
          <div>
            <Label className="text-xs">Node Name</Label>
            <Input
              value={(node.data.label as string) || ""}
              onChange={(e) => onUpdateNode(node.id, { label: e.target.value })}
              className="mt-1 h-8 text-sm"
            />
          </div>

          {/* Type-specific config */}
          {nodeType === "voice_call" && (
            <>
              <div>
                <Label className="text-xs">Bot</Label>
                <Select
                  value={config.bot_id || ""}
                  onValueChange={(v) => updateConfig("bot_id", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue placeholder="Select a bot" />
                  </SelectTrigger>
                  <SelectContent>
                    {bots.map((bot) => (
                      <SelectItem key={bot.id} value={bot.id}>
                        {bot.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs">Quick Retry</Label>
                <Switch
                  checked={config.quick_retry?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("quick_retry", "enabled", v)}
                />
              </div>
              {config.quick_retry?.enabled && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Max Attempts</Label>
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      value={config.quick_retry.max_attempts ?? 3}
                      onChange={(e) => updateNestedConfig("quick_retry", "max_attempts", parseInt(e.target.value) || 3)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Interval (hrs)</Label>
                    <Input
                      type="number"
                      min={0.5}
                      step={0.5}
                      value={config.quick_retry.interval_hours ?? 1}
                      onChange={(e) => updateNestedConfig("quick_retry", "interval_hours", parseFloat(e.target.value) || 1)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                </div>
              )}
            </>
          )}

          {nodeType === "whatsapp_template" && (
            <>
              <div>
                <Label className="text-xs">Template Name</Label>
                <Input
                  value={config.template_name || ""}
                  onChange={(e) => updateConfig("template_name", e.target.value)}
                  className="mt-1 h-8 text-sm"
                  placeholder="e.g., follow_up_v1"
                />
              </div>
            </>
          )}

          {nodeType === "whatsapp_session" && (
            <>
              <div className="flex items-center justify-between">
                <Label className="text-xs">AI Generation</Label>
                <Switch
                  checked={config.ai_generation?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("ai_generation", "enabled", v)}
                />
              </div>
              {config.ai_generation?.enabled ? (
                <div>
                  <Label className="text-xs">AI Prompt</Label>
                  <Textarea
                    value={config.ai_generation.prompt || ""}
                    onChange={(e) => updateNestedConfig("ai_generation", "prompt", e.target.value)}
                    className="mt-1 min-h-[80px] text-sm"
                    placeholder="Write a follow-up for {{contact_name}}..."
                  />
                </div>
              ) : (
                <div>
                  <Label className="text-xs">Static Message</Label>
                  <Textarea
                    value={config.message || ""}
                    onChange={(e) => updateConfig("message", e.target.value)}
                    className="mt-1 min-h-[80px] text-sm"
                    placeholder="Hi {{contact_name}}..."
                  />
                </div>
              )}
              <div className="flex items-center justify-between">
                <Label className="text-xs">Expects Reply</Label>
                <Switch
                  checked={config.expects_reply ?? false}
                  onCheckedChange={(v) => updateConfig("expects_reply", v)}
                />
              </div>
            </>
          )}

          {nodeType === "ai_generate_send" && (
            <>
              <div>
                <Label className="text-xs">Mode</Label>
                <Select
                  value={config.mode || "full_message"}
                  onValueChange={(v) => updateConfig("mode", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="full_message">Full Message</SelectItem>
                    <SelectItem value="fill_template_vars">Fill Template Vars</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Prompt</Label>
                <Textarea
                  value={config.prompt || ""}
                  onChange={(e) => updateConfig("prompt", e.target.value)}
                  className="mt-1 min-h-[80px] text-sm"
                  placeholder="Generate a message for {{contact_name}}..."
                />
              </div>
              <div>
                <Label className="text-xs">Send Via</Label>
                <Select
                  value={config.send_via || "whatsapp_session"}
                  onValueChange={(v) => updateConfig("send_via", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="whatsapp_session">WhatsApp Session</SelectItem>
                    <SelectItem value="whatsapp_template">WhatsApp Template</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {nodeType === "condition" && (
            <>
              <p className="text-xs text-muted-foreground">
                Condition branches are configured as outgoing edges. Add rules to determine which branch a lead follows.
              </p>
              <div>
                <Label className="text-xs">Default Branch Label</Label>
                <Input
                  value={config.default_label || "other"}
                  onChange={(e) => updateConfig("default_label", e.target.value)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
              {/* Full condition editor is complex — placeholder for v1 */}
              <p className="text-[11px] text-muted-foreground italic">
                Condition rules editor coming in next iteration. Use JSON config for now.
              </p>
            </>
          )}

          {nodeType === "delay_wait" && (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Duration</Label>
                <Input
                  type="number"
                  min={0}
                  value={config.duration_value ?? 1}
                  onChange={(e) => updateConfig("duration_value", parseInt(e.target.value) || 1)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
              <div>
                <Label className="text-xs">Unit</Label>
                <Select
                  value={config.duration_unit || "hours"}
                  onValueChange={(v) => updateConfig("duration_unit", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="minutes">Minutes</SelectItem>
                    <SelectItem value="hours">Hours</SelectItem>
                    <SelectItem value="days">Days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {nodeType === "wait_for_event" && (
            <>
              <div>
                <Label className="text-xs">Event Type</Label>
                <Select
                  value={config.event_type || "reply_received"}
                  onValueChange={(v) => updateConfig("event_type", v)}
                >
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="reply_received">Reply Received</SelectItem>
                    <SelectItem value="call_completed">Call Completed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Timeout (hours)</Label>
                <Input
                  type="number"
                  min={1}
                  value={config.timeout_hours ?? 24}
                  onChange={(e) => updateConfig("timeout_hours", parseInt(e.target.value) || 24)}
                  className="mt-1 h-8 text-sm"
                />
              </div>
            </>
          )}

          {nodeType === "goal_met" && (
            <>
              <div>
                <Label className="text-xs">Goal Name</Label>
                <Input
                  value={config.goal_name || ""}
                  onChange={(e) => updateConfig("goal_name", e.target.value)}
                  className="mt-1 h-8 text-sm"
                  placeholder="e.g., booking_confirmed"
                />
              </div>
              <div>
                <Label className="text-xs">Description</Label>
                <Textarea
                  value={config.goal_description || ""}
                  onChange={(e) => updateConfig("goal_description", e.target.value)}
                  className="mt-1 min-h-[60px] text-sm"
                  placeholder="What does this goal represent?"
                />
              </div>
            </>
          )}

          {nodeType === "end" && (
            <div>
              <Label className="text-xs">End Reason</Label>
              <Select
                value={config.end_reason || "completed"}
                onValueChange={(v) => updateConfig("end_reason", v)}
              >
                <SelectTrigger className="mt-1 h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="disqualified">Disqualified</SelectItem>
                  <SelectItem value="unresponsive">Unresponsive</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Send window — shared by action nodes */}
          {["voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send", "delay_wait"].includes(nodeType) && (
            <div className="border-t pt-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">Send Window</Label>
                <Switch
                  checked={config.send_window?.enabled ?? false}
                  onCheckedChange={(v) => updateNestedConfig("send_window", "enabled", v)}
                />
              </div>
              {config.send_window?.enabled && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Start</Label>
                    <Input
                      type="time"
                      value={config.send_window.start || config.send_window.resume_at || "09:00"}
                      onChange={(e) => {
                        updateNestedConfig("send_window", "start", e.target.value);
                        updateNestedConfig("send_window", "resume_at", e.target.value);
                      }}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">End</Label>
                    <Input
                      type="time"
                      value={config.send_window.end || "19:00"}
                      onChange={(e) => updateNestedConfig("send_window", "end", e.target.value)}
                      className="mt-1 h-8 text-sm"
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
