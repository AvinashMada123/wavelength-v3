"use client";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GitBranch, Zap } from "lucide-react";

interface OutcomePickerPopoverProps {
  /** Labels from the outgoing edges of the current condition node */
  outcomeLabels: string[];
  /** The auto-evaluated label (highlighted as recommended) */
  autoLabel?: string;
  onPick: (label: string) => void;
  onAutoEvaluate: () => void;
}

export function OutcomePickerPopover({
  outcomeLabels,
  autoLabel,
  onPick,
  onAutoEvaluate,
}: OutcomePickerPopoverProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="sm" variant="secondary" className="gap-1.5">
          <GitBranch className="h-3.5 w-3.5" />
          Pick Outcome
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-2" align="center">
        <div className="space-y-1">
          <Button
            size="sm"
            variant="ghost"
            className="w-full justify-start gap-2 text-blue-500"
            onClick={onAutoEvaluate}
          >
            <Zap className="h-3.5 w-3.5" />
            Auto-evaluate
          </Button>
          <div className="my-1 border-t" />
          {outcomeLabels.map((label) => (
            <Button
              key={label}
              size="sm"
              variant="ghost"
              className={`w-full justify-start ${label === autoLabel ? "font-semibold text-green-600" : ""}`}
              onClick={() => onPick(label)}
            >
              {label}
              {label === autoLabel && (
                <span className="ml-auto text-xs text-muted-foreground">recommended</span>
              )}
            </Button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
