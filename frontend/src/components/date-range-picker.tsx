"use client";

import { useState, useMemo, useCallback } from "react";
import { CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

// -- Types --

export interface DateRange {
  from: string | null; // YYYY-MM-DD or YYYY-MM-DDTHH:MM
  to: string | null;
}

type PresetKey = "today" | "7d" | "30d" | "90d" | "custom";

interface Preset {
  key: PresetKey;
  label: string;
}

const PRESETS: Preset[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "90d", label: "Last 90 days" },
  { key: "custom", label: "Custom" },
];

// -- Helpers --

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getPresetRange(key: PresetKey): DateRange {
  const end = new Date();
  const start = new Date();
  switch (key) {
    case "today":
      start.setHours(0, 0, 0, 0);
      break;
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "30d":
      start.setDate(start.getDate() - 30);
      break;
    case "90d":
      start.setDate(start.getDate() - 90);
      break;
    case "custom":
      return { from: null, to: null };
  }
  return { from: toISODate(start), to: toISODate(end) };
}

/** Extract just the date part from a date or datetime string */
function datePartOf(str: string): string {
  return str.slice(0, 10);
}

/** Extract time part (HH:MM) or null */
function timePartOf(str: string): string | null {
  if (str.length > 10 && str[10] === "T") return str.slice(11, 16);
  return null;
}

function formatDisplayDate(dateStr: string): string {
  const datePart = datePartOf(dateStr);
  const timePart = timePartOf(dateStr);
  const d = new Date(datePart + "T00:00:00");
  const dateLabel = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  if (timePart) return `${dateLabel} ${timePart}`;
  return dateLabel;
}

function detectPreset(range: DateRange): PresetKey {
  if (!range.from || !range.to) return "custom";
  // If time components are present, it's custom
  if (timePartOf(range.from) || timePartOf(range.to)) return "custom";
  const today = toISODate(new Date());
  if (datePartOf(range.to) !== today) return "custom";

  for (const p of PRESETS) {
    if (p.key === "custom") continue;
    const pr = getPresetRange(p.key);
    if (pr.from === range.from && pr.to === range.to) return p.key;
  }
  return "custom";
}

// -- Component --

interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  className?: string;
  enableTime?: boolean;
}

export function DateRangePicker({
  value,
  onChange,
  className,
  enableTime = false,
}: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const activePreset = useMemo(() => detectPreset(value), [value]);

  const displayLabel = useMemo(() => {
    if (!value.from && !value.to) return "Select dates";
    const preset = PRESETS.find((p) => p.key === activePreset);
    if (activePreset !== "custom" && preset) return preset.label;
    if (value.from && value.to) {
      return `${formatDisplayDate(value.from)} - ${formatDisplayDate(value.to)}`;
    }
    if (value.from) return `From ${formatDisplayDate(value.from)}`;
    if (value.to) return `To ${formatDisplayDate(value.to)}`;
    return "Select dates";
  }, [value, activePreset]);

  const handlePresetClick = useCallback(
    (key: PresetKey) => {
      if (key === "custom") return;
      const range = getPresetRange(key);
      onChange(range);
      setOpen(false);
    },
    [onChange]
  );

  const [showCustom, setShowCustom] = useState(activePreset === "custom");

  // Derived date/time parts for custom inputs
  const fromDate = value.from ? datePartOf(value.from) : "";
  const fromTime = value.from ? (timePartOf(value.from) || "") : "";
  const toDate = value.to ? datePartOf(value.to) : "";
  const toTime = value.to ? (timePartOf(value.to) || "") : "";

  const buildValue = (date: string, time: string): string | null => {
    if (!date) return null;
    if (time) return `${date}T${time}`;
    return date;
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="default"
          className={cn(
            "h-9 gap-2 text-sm font-normal",
            !value.from && !value.to && "text-muted-foreground",
            className
          )}
        >
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
          {displayLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-3">
        <div className="space-y-2">
          {/* Preset buttons */}
          <div className="grid grid-cols-2 gap-1.5">
            {PRESETS.filter((p) => p.key !== "custom").map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => {
                  handlePresetClick(preset.key);
                  setShowCustom(false);
                }}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors text-left",
                  activePreset === preset.key && !showCustom
                    ? "bg-violet-500/15 text-violet-400 font-medium"
                    : "hover:bg-muted text-muted-foreground hover:text-foreground"
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {/* Custom toggle */}
          <button
            type="button"
            onClick={() => setShowCustom(true)}
            className={cn(
              "w-full rounded-md px-3 py-1.5 text-sm transition-colors text-left",
              showCustom || activePreset === "custom"
                ? "bg-violet-500/15 text-violet-400 font-medium"
                : "hover:bg-muted text-muted-foreground hover:text-foreground"
            )}
          >
            Custom Range
          </button>

          {/* Custom date inputs */}
          {(showCustom || activePreset === "custom") && (
            <div className="space-y-2 pt-2 border-t border-border">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  From
                </label>
                <div className={cn("flex gap-1.5", enableTime ? "" : "")}>
                  <input
                    type="date"
                    value={fromDate}
                    onChange={(e) =>
                      onChange({ ...value, from: buildValue(e.target.value, fromTime) })
                    }
                    max={toDate || toISODate(new Date())}
                    className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                  />
                  {enableTime && (
                    <input
                      type="time"
                      value={fromTime}
                      onChange={(e) =>
                        onChange({ ...value, from: buildValue(fromDate, e.target.value) })
                      }
                      className="w-[100px] rounded-md border border-input bg-background px-2 py-1.5 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                    />
                  )}
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  To
                </label>
                <div className="flex gap-1.5">
                  <input
                    type="date"
                    value={toDate}
                    onChange={(e) =>
                      onChange({ ...value, to: buildValue(e.target.value, toTime) })
                    }
                    min={fromDate || undefined}
                    max={toISODate(new Date())}
                    className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                  />
                  {enableTime && (
                    <input
                      type="time"
                      value={toTime}
                      onChange={(e) =>
                        onChange({ ...value, to: buildValue(toDate, e.target.value) })
                      }
                      className="w-[100px] rounded-md border border-input bg-background px-2 py-1.5 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
                    />
                  )}
                </div>
              </div>
              <Button
                size="sm"
                className="w-full bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                onClick={() => setOpen(false)}
                disabled={!value.from || !value.to}
              >
                Apply
              </Button>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// -- Utility: Convert DateRange to start/end strings for API calls --
// Returns { start: string; end: string } with defaults if null

export function getDateRangeValues(
  range: DateRange,
  defaultDays: number = 30
): { start: string; end: string } {
  const end = range.to || toISODate(new Date());
  let start = range.from;
  if (!start) {
    const d = new Date();
    d.setDate(d.getDate() - defaultDays);
    start = toISODate(d);
  }
  return { start, end };
}

// -- Utility: Create initial DateRange from preset --

export function createDateRange(preset: "today" | "7d" | "30d" | "90d"): DateRange {
  return getPresetRange(preset);
}
