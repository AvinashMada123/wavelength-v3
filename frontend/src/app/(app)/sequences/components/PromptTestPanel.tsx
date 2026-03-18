"use client";

import { useState, useMemo, useCallback } from "react";
import {
  X,
  Sparkles,
  Loader2,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Cpu,
  Clock,
  DollarSign,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { testPrompt, type PromptTestResult } from "@/lib/sequences-api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract {{variable}} names from prompt string */
function extractVariables(prompt: string): string[] {
  const matches = prompt.match(/\{\{(\w+)\}\}/g);
  if (!matches) return [];
  return [...new Set(matches.map((m) => m.replace(/[{}]/g, "")))];
}

/** Highlight {{variables}} in prompt text */
function highlightVariables(prompt: string) {
  const parts = prompt.split(/(\{\{\w+\}\})/g);
  return parts.map((part, i) =>
    /^\{\{\w+\}\}$/.test(part) ? (
      <span
        key={i}
        className="rounded bg-violet-100 px-1 font-semibold text-violet-700 dark:bg-violet-900/40 dark:text-violet-300"
      >
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

const MODEL_OPTIONS = [
  { value: "claude-sonnet", label: "Claude Sonnet" },
  { value: "claude-haiku", label: "Claude Haiku" },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface PromptTestPanelProps {
  isOpen: boolean;
  onClose: () => void;
  prompt: string;
  model: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PromptTestPanel({
  isOpen,
  onClose,
  prompt,
  model: initialModel,
}: PromptTestPanelProps) {
  const variables = useMemo(() => extractVariables(prompt), [prompt]);
  const [varValues, setVarValues] = useState<Record<string, string>>({});
  const [selectedModel, setSelectedModel] = useState(initialModel);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<PromptTestResult[]>([]);
  const [expandedResult, setExpandedResult] = useState<number | null>(null);

  const latestResult = results[0] ?? null;

  const handleGenerate = useCallback(async () => {
    setLoading(true);
    try {
      const result = await testPrompt({
        prompt,
        variables: varValues,
        model: selectedModel,
      });
      setResults((prev) => [result, ...prev].slice(0, 5));
      setExpandedResult(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Prompt test failed";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [prompt, varValues, selectedModel]);

  if (!isOpen) return null;

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l bg-background shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-500" />
            <h2 className="text-sm font-semibold">Test Prompt</h2>
          </div>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="space-y-5 p-5">
            {/* Prompt display */}
            <div className="space-y-1.5">
              <Label className="text-xs">Prompt</Label>
              <div className="rounded-lg border bg-muted/50 p-3 text-sm leading-relaxed whitespace-pre-wrap">
                {highlightVariables(prompt)}
              </div>
            </div>

            {/* Variable inputs */}
            {variables.length > 0 && (
              <div className="space-y-3">
                <Label className="text-xs">Variables</Label>
                {variables.map((v) => (
                  <div key={v} className="space-y-1">
                    <Label className="text-[10px] text-muted-foreground">
                      {`{{${v}}}`}
                    </Label>
                    <Input
                      placeholder={`Value for ${v}`}
                      value={varValues[v] ?? ""}
                      onChange={(e) =>
                        setVarValues((prev) => ({ ...prev, [v]: e.target.value }))
                      }
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Model selector */}
            <div className="space-y-1.5">
              <Label className="text-xs">Model</Label>
              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODEL_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Generate button */}
            <Button
              className="w-full bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              onClick={handleGenerate}
              disabled={loading}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkles className="mr-1.5 h-4 w-4" />
                  Generate
                </>
              )}
            </Button>

            {/* Latest result */}
            {latestResult && (
              <div className="space-y-3">
                <Label className="text-xs">Generated Output</Label>
                <div className="rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">
                  {latestResult.generated_content}
                </div>

                {/* Stats */}
                <div className="flex flex-wrap gap-3">
                  <Badge variant="outline" className="gap-1 text-xs">
                    <Cpu className="h-3 w-3" />
                    {latestResult.tokens_used} tokens
                  </Badge>
                  <Badge variant="outline" className="gap-1 text-xs">
                    <Clock className="h-3 w-3" />
                    {latestResult.latency_ms}ms
                  </Badge>
                  <Badge variant="outline" className="gap-1 text-xs">
                    <DollarSign className="h-3 w-3" />
                    ${latestResult.cost_estimate.toFixed(4)}
                  </Badge>
                </div>

                {/* Try again */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleGenerate}
                  disabled={loading}
                >
                  <RotateCcw className="mr-1 h-3 w-3" />
                  Try Again
                </Button>
              </div>
            )}

            {/* Previous results */}
            {results.length > 1 && (
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Previous Results</Label>
                {results.slice(1).map((result, idx) => {
                  const realIdx = idx + 1;
                  const isOpen = expandedResult === realIdx;
                  return (
                    <div key={realIdx} className="rounded-lg border">
                      <button
                        type="button"
                        className="flex w-full items-center justify-between p-3 text-left text-xs hover:bg-muted/50"
                        onClick={() =>
                          setExpandedResult(isOpen ? null : realIdx)
                        }
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">
                            Run #{results.length - realIdx}
                          </span>
                          <Badge variant="outline" className="text-[10px]">
                            {result.model}
                          </Badge>
                          <Badge variant="outline" className="text-[10px]">
                            {result.latency_ms}ms
                          </Badge>
                        </div>
                        {isOpen ? (
                          <ChevronUp className="h-3 w-3 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-3 w-3 text-muted-foreground" />
                        )}
                      </button>
                      {isOpen && (
                        <div className="border-t p-3 text-sm leading-relaxed whitespace-pre-wrap">
                          {result.generated_content}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </>
  );
}
