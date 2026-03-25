// frontend/src/components/flow/CanvasToolbar.tsx
"use client";

import { useReactFlow } from "@xyflow/react";
import {
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  LayoutGrid,
  CheckCircle2,
  Rocket,
  Play,
  Save,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CanvasToolbarProps {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onAutoLayout: () => void;
  onValidate: () => void;
  onPublish: () => void;
  onSimulate: () => void;
  onSave: () => void;
  isPublishing: boolean;
  isValidating: boolean;
  isSaving: boolean;
  isDirty: boolean;
  isDraft: boolean;
}

export function CanvasToolbar({
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onAutoLayout,
  onValidate,
  onPublish,
  onSimulate,
  onSave,
  isPublishing,
  isValidating,
  isSaving,
  isDirty,
  isDraft,
}: CanvasToolbarProps) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex items-center gap-1 rounded-lg border bg-background/95 px-2 py-1 shadow-sm backdrop-blur">
        {/* Undo/Redo */}
        <ToolbarButton icon={Undo2} label="Undo (Ctrl+Z)" onClick={onUndo} disabled={!canUndo} />
        <ToolbarButton icon={Redo2} label="Redo (Ctrl+Y)" onClick={onRedo} disabled={!canRedo} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Zoom */}
        <ToolbarButton icon={ZoomIn} label="Zoom In" onClick={() => zoomIn()} />
        <ToolbarButton icon={ZoomOut} label="Zoom Out" onClick={() => zoomOut()} />
        <ToolbarButton icon={Maximize2} label="Fit View" onClick={() => fitView({ padding: 0.2 })} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Layout */}
        <ToolbarButton icon={LayoutGrid} label="Auto Layout" onClick={onAutoLayout} />

        <Separator orientation="vertical" className="mx-1 h-6" />

        {/* Actions */}
        <ToolbarButton
          icon={Play}
          label="Simulate"
          onClick={onSimulate}
        />

        <ToolbarButton
          icon={isValidating ? Loader2 : CheckCircle2}
          label="Validate"
          onClick={onValidate}
          disabled={isValidating}
          iconClassName={isValidating ? "animate-spin" : ""}
        />

        {isDraft && (
          <>
            <Button
              size="sm"
              variant={isDirty ? "default" : "ghost"}
              onClick={onSave}
              disabled={isSaving || !isDirty}
              className="ml-1 h-7 gap-1.5 px-3 text-xs"
            >
              {isSaving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              {isSaving ? "Saving..." : "Save"}
            </Button>
            <Button
              size="sm"
              onClick={onPublish}
              disabled={isPublishing}
              className="ml-1 h-7 gap-1.5 px-3 text-xs"
            >
              {isPublishing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Rocket className="h-3.5 w-3.5" />
              )}
              Publish
            </Button>
          </>
        )}
      </div>
    </TooltipProvider>
  );
}

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  iconClassName,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  iconClassName?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClick}
          disabled={disabled}
          className="h-7 w-7 p-0"
        >
          <Icon className={`h-4 w-4 ${iconClassName || ""}`} />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
