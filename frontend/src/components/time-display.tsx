"use client";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { timeAgo, formatDate } from "@/lib/utils";

interface TimeDisplayProps {
  date: string;
  className?: string;
}

export function TimeDisplay({ date, className }: TimeDisplayProps) {
  if (!date) return <span className={className}>--</span>;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={className}>{timeAgo(date)}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p>{formatDate(date)}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
