// frontend/src/components/flow/TemplatePicker.tsx
"use client";

import { useState } from "react";
import {
  FileText,
  PhoneForwarded,
  PhoneMissed,
  Sprout,
  Loader2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { FLOW_TEMPLATES, type FlowTemplate } from "@/lib/flow-templates";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  FileText, PhoneForwarded, PhoneMissed, Sprout,
};

interface TemplatePickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, templateId: string) => Promise<void>;
}

export function TemplatePicker({ open, onOpenChange, onCreate }: TemplatePickerProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<string>("blank");
  const [flowName, setFlowName] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!flowName.trim()) return;
    setCreating(true);
    try {
      await onCreate(flowName.trim(), selectedTemplate);
      setFlowName("");
      setSelectedTemplate("blank");
      onOpenChange(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create New Flow</DialogTitle>
          <DialogDescription>
            Choose a template to get started, or begin with a blank flow.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label className="text-sm">Flow Name</Label>
            <Input
              value={flowName}
              onChange={(e) => setFlowName(e.target.value)}
              placeholder="e.g., Post-Call Follow-Up"
              className="mt-1"
              autoFocus
            />
          </div>

          <div>
            <Label className="text-sm">Template</Label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {FLOW_TEMPLATES.map((tmpl) => {
                const Icon = ICON_MAP[tmpl.icon] || FileText;
                return (
                  <button
                    key={tmpl.id}
                    onClick={() => setSelectedTemplate(tmpl.id)}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent",
                      selectedTemplate === tmpl.id && "border-primary bg-accent",
                    )}
                  >
                    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{tmpl.name}</p>
                      <p className="text-xs text-muted-foreground">{tmpl.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <Button
            onClick={handleCreate}
            disabled={!flowName.trim() || creating}
            className="w-full"
          >
            {creating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Creating...
              </>
            ) : (
              "Create Flow"
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
