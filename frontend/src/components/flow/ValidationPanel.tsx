// frontend/src/components/flow/ValidationPanel.tsx
"use client";

import { AlertTriangle, XCircle, CheckCircle2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ValidationResult } from "@/lib/flow-types";

interface ValidationPanelProps {
  result: ValidationResult | null;
  onClose: () => void;
  onFocusNode: (nodeId: string) => void;
}

export function ValidationPanel({ result, onClose, onFocusNode }: ValidationPanelProps) {
  if (!result) return null;

  return (
    <div className="absolute bottom-4 left-1/2 z-10 w-[420px] -translate-x-1/2 rounded-lg border bg-background shadow-lg">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          {result.valid ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <XCircle className="h-4 w-4 text-red-500" />
          )}
          <span className="text-sm font-medium">
            {result.valid ? "Validation passed" : `${result.errors.length} error(s) found`}
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-6 w-6 p-0">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="max-h-48 overflow-y-auto p-2">
        {result.errors.map((issue, i) => (
          <button
            key={`err-${i}`}
            className={cn(
              "flex w-full items-start gap-2 rounded-md px-3 py-1.5 text-left text-xs hover:bg-accent",
              issue.node_id && "cursor-pointer",
            )}
            onClick={() => issue.node_id && onFocusNode(issue.node_id)}
          >
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
            <span>{issue.message}</span>
          </button>
        ))}
        {result.warnings.map((issue, i) => (
          <button
            key={`warn-${i}`}
            className={cn(
              "flex w-full items-start gap-2 rounded-md px-3 py-1.5 text-left text-xs hover:bg-accent",
              issue.node_id && "cursor-pointer",
            )}
            onClick={() => issue.node_id && onFocusNode(issue.node_id)}
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span>{issue.message}</span>
          </button>
        ))}
        {result.errors.length === 0 && result.warnings.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No issues found. Ready to publish.</p>
        )}
      </div>
    </div>
  );
}
