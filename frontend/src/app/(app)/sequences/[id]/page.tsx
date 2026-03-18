"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  Plus,
  ChevronUp,
  ChevronDown,
  Download,
  Loader2,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  fetchTemplate,
  updateTemplate,
  addStep,
  updateStep,
  deleteStep,
  reorderSteps,
  exportTemplate,
  type SequenceTemplate,
  type SequenceStep,
} from "@/lib/sequences-api";
import { fetchBots } from "@/lib/api";
import { StepCard } from "../components/StepCard";
import { PromptTestPanel } from "../components/PromptTestPanel";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TRIGGER_TYPE_OPTIONS = [
  { value: "post_call", label: "Post Call" },
  { value: "manual", label: "Manual" },
  { value: "campaign_complete", label: "Campaign Complete" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TemplateBuilderPage() {
  const router = useRouter();
  const params = useParams();
  const templateId = params.id as string;

  // Template state
  const [template, setTemplate] = useState<SequenceTemplate | null>(null);
  const [steps, setSteps] = useState<SequenceStep[]>([]);
  const [loading, setLoading] = useState(true);

  // Bots for voice_call step type
  const [bots, setBots] = useState<{ id: string; name: string }[]>([]);

  // Editable header fields
  const [templateName, setTemplateName] = useState("");
  const [triggerType, setTriggerType] = useState("post_call");
  const [isActive, setIsActive] = useState(false);

  // UI state
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null);
  const [addingStep, setAddingStep] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [savingHeader, setSavingHeader] = useState(false);

  // Prompt test panel
  const [testPanelOpen, setTestPanelOpen] = useState(false);
  const [testPromptText, setTestPromptText] = useState("");
  const [testModel, setTestModel] = useState("claude-sonnet");

  // -----------------------------------------------------------------------
  // Load data
  // -----------------------------------------------------------------------

  const loadTemplate = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTemplate(templateId);
      setTemplate(data);
      setSteps(data.steps.sort((a, b) => a.step_order - b.step_order));
      setTemplateName(data.name);
      setTriggerType(data.trigger_type);
      setIsActive(data.is_active);
    } catch {
      toast.error("Failed to load template");
    } finally {
      setLoading(false);
    }
  }, [templateId]);

  const loadBots = useCallback(async () => {
    try {
      const data = await fetchBots();
      setBots(data.map((b) => ({ id: b.id, name: b.agent_name || b.company_name || "Unnamed" })));
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    loadTemplate();
    loadBots();
  }, [loadTemplate, loadBots]);

  // -----------------------------------------------------------------------
  // Header save (debounced on blur)
  // -----------------------------------------------------------------------

  const saveHeader = useCallback(
    async (patch: Partial<SequenceTemplate>) => {
      if (!template) return;
      setSavingHeader(true);
      try {
        const updated = await updateTemplate(templateId, patch);
        setTemplate((prev) => (prev ? { ...prev, ...updated } : prev));
      } catch {
        toast.error("Failed to save template");
      } finally {
        setSavingHeader(false);
      }
    },
    [template, templateId],
  );

  // -----------------------------------------------------------------------
  // Step operations
  // -----------------------------------------------------------------------

  const handleUpdateStep = useCallback(
    async (stepId: string, data: Partial<SequenceStep>) => {
      try {
        const updated = await updateStep(stepId, data);
        setSteps((prev) =>
          prev.map((s) => (s.id === stepId ? { ...s, ...updated } : s)),
        );
      } catch {
        toast.error("Failed to update step");
      }
    },
    [],
  );

  const handleDeleteStep = useCallback(
    async (stepId: string) => {
      try {
        await deleteStep(stepId);
        setSteps((prev) => prev.filter((s) => s.id !== stepId));
        toast.success("Step deleted");
      } catch {
        toast.error("Failed to delete step");
      }
    },
    [],
  );

  const handleAddStep = useCallback(async () => {
    setAddingStep(true);
    try {
      const nextOrder = steps.length > 0 ? Math.max(...steps.map((s) => s.step_order)) + 1 : 1;
      const newStep = await addStep(templateId, {
        name: `Step ${nextOrder}`,
        step_order: nextOrder,
        channel: "whatsapp_template",
        timing_type: "delay",
        timing_value: { hours: 1 },
        content_type: "static_template",
        is_active: true,
      });
      setSteps((prev) => [...prev, newStep]);
      setExpandedStepId(newStep.id);
      toast.success("Step added");
    } catch {
      toast.error("Failed to add step");
    } finally {
      setAddingStep(false);
    }
  }, [steps, templateId]);

  const handleMoveStep = useCallback(
    async (stepId: string, direction: "up" | "down") => {
      const idx = steps.findIndex((s) => s.id === stepId);
      if (idx < 0) return;
      const swapIdx = direction === "up" ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= steps.length) return;

      const reordered = [...steps];
      [reordered[idx], reordered[swapIdx]] = [reordered[swapIdx], reordered[idx]];
      // Update step_order locally
      const withOrder = reordered.map((s, i) => ({ ...s, step_order: i + 1 }));
      setSteps(withOrder);

      try {
        await reorderSteps(templateId, withOrder.map((s) => s.id));
      } catch {
        toast.error("Failed to reorder steps");
        loadTemplate(); // revert
      }
    },
    [steps, templateId, loadTemplate],
  );

  const handleTestPrompt = useCallback((prompt: string, model: string) => {
    setTestPromptText(prompt);
    setTestModel(model);
    setTestPanelOpen(true);
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const data = await exportTemplate(templateId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${templateName || "template"}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Template exported");
    } catch {
      toast.error("Failed to export template");
    } finally {
      setExporting(false);
    }
  }, [templateId, templateName]);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  if (loading) {
    return (
      <>
        <Header title="Template Builder" />
        <PageTransition>
          <div className="space-y-4 p-6">
            <Skeleton className="h-10 w-72" />
            <Skeleton className="h-8 w-48" />
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          </div>
        </PageTransition>
      </>
    );
  }

  if (!template) {
    return (
      <>
        <Header title="Template Builder" />
        <PageTransition>
          <div className="flex flex-col items-center justify-center py-24 text-muted-foreground">
            <p className="text-sm">Template not found</p>
            <Button variant="link" size="sm" onClick={() => router.push("/sequences")}>
              Back to templates
            </Button>
          </div>
        </PageTransition>
      </>
    );
  }

  return (
    <>
      <Header title="Template Builder" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Back + header actions */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              <Button
                variant="ghost"
                size="sm"
                className="mt-0.5 h-8 w-8 p-0"
                onClick={() => router.push("/sequences")}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <div className="space-y-2 flex-1 min-w-0">
                <Input
                  className="text-lg font-semibold border-none shadow-none px-0 focus-visible:ring-0 h-auto"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  onBlur={() => {
                    if (templateName !== template.name) {
                      saveHeader({ name: templateName });
                    }
                  }}
                  placeholder="Template name"
                />
                <div className="flex items-center gap-3">
                  <Select
                    value={triggerType}
                    onValueChange={(val) => {
                      setTriggerType(val);
                      saveHeader({ trigger_type: val });
                    }}
                  >
                    <SelectTrigger className="h-8 w-44 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TRIGGER_TYPE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="flex items-center gap-1.5">
                    <Switch
                      checked={isActive}
                      onCheckedChange={(checked) => {
                        setIsActive(checked);
                        saveHeader({ is_active: checked });
                      }}
                    />
                    <Label className="text-xs text-muted-foreground">Active</Label>
                  </div>

                  {savingHeader && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                  )}
                </div>
              </div>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exporting}
            >
              {exporting ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="mr-1 h-3.5 w-3.5" />
              )}
              Export JSON
            </Button>
          </div>

          {/* Steps list */}
          {steps.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-muted-foreground">
              <Workflow className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm font-medium">No steps yet</p>
              <p className="mt-1 text-xs">Add your first step to build the sequence</p>
            </div>
          ) : (
            <div className="space-y-3">
              {steps.map((step, idx) => (
                <div key={step.id} className="flex items-start gap-2">
                  {/* Move buttons */}
                  <div className="flex flex-col gap-0.5 pt-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0"
                      disabled={idx === 0}
                      onClick={() => handleMoveStep(step.id, "up")}
                    >
                      <ChevronUp className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0"
                      disabled={idx === steps.length - 1}
                      onClick={() => handleMoveStep(step.id, "down")}
                    >
                      <ChevronDown className="h-3.5 w-3.5" />
                    </Button>
                  </div>

                  {/* Step card */}
                  <div className="flex-1">
                    <StepCard
                      step={step}
                      bots={bots}
                      onUpdate={handleUpdateStep}
                      onDelete={handleDeleteStep}
                      onTestPrompt={handleTestPrompt}
                      isExpanded={expandedStepId === step.id}
                      onToggleExpand={() =>
                        setExpandedStepId(
                          expandedStepId === step.id ? null : step.id,
                        )
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Add Step button */}
          <Button
            variant="outline"
            className="w-full border-dashed"
            onClick={handleAddStep}
            disabled={addingStep}
          >
            {addingStep ? (
              <>
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                Adding...
              </>
            ) : (
              <>
                <Plus className="mr-1.5 h-4 w-4" />
                Add Step
              </>
            )}
          </Button>
        </div>
      </PageTransition>

      {/* Prompt test panel */}
      <PromptTestPanel
        isOpen={testPanelOpen}
        onClose={() => setTestPanelOpen(false)}
        prompt={testPromptText}
        model={testModel}
      />
    </>
  );
}
