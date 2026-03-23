"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Play,
  SkipForward,
  Square,
  RotateCcw,
  FlaskConical,
  FastForward,
} from "lucide-react";
import { MockLeadDialog } from "./MockLeadDialog";
import { OutcomePickerPopover } from "./OutcomePickerPopover";
import type { UseFlowSimulationReturn } from "@/hooks/use-flow-simulation";
import type { FlowGraph } from "@/lib/flow-simulation";

interface SimulationToolbarProps {
  simulation: UseFlowSimulationReturn;
  graph: FlowGraph;
}

export function SimulationToolbar({ simulation, graph }: SimulationToolbarProps) {
  const [mockLeadOpen, setMockLeadOpen] = useState(false);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);

  const currentNode = simulation.simulationState
    ? graph.nodes.find((n) => n.id === simulation.simulationState!.currentNodeId)
    : null;

  const isCondition = currentNode?.type === "condition";
  const isCompleted = simulation.simulationState?.status === "completed";

  // Get outgoing edge labels for condition nodes
  const outcomeLabels = isCondition
    ? graph.edges
        .filter((e) => e.source === currentNode!.id)
        .map((e) => e.condition_label)
    : [];

  function handleAutoPlay() {
    if (isAutoPlaying) {
      simulation.stopAutoPlay();
      setIsAutoPlaying(false);
    } else {
      simulation.autoPlay(800);
      setIsAutoPlaying(true);
    }
  }

  if (!simulation.isActive) {
    return (
      <>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          onClick={() => setMockLeadOpen(true)}
        >
          <FlaskConical className="h-3.5 w-3.5" />
          Simulate
        </Button>
        <MockLeadDialog
          open={mockLeadOpen}
          onOpenChange={setMockLeadOpen}
          onStart={simulation.start}
        />
      </>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border bg-background/95 px-3 py-2 shadow-lg backdrop-blur">
      <Badge variant="secondary" className="bg-green-100 text-green-800">
        Simulating
      </Badge>

      {currentNode && (
        <span className="text-sm text-muted-foreground">
          @ <strong>{currentNode.name}</strong>
        </span>
      )}

      {/* Action preview */}
      {simulation.actionPreview && !isCondition && (
        <span className="max-w-xs truncate text-xs text-muted-foreground">
          {simulation.actionPreview.description}
        </span>
      )}

      <div className="mx-1 h-4 border-l" />

      {/* Step controls */}
      {!isCompleted && !isCondition && (
        <Button size="sm" variant="ghost" className="gap-1" onClick={() => simulation.next("default")}>
          <SkipForward className="h-3.5 w-3.5" />
          Next
        </Button>
      )}

      {/* Condition node: outcome picker */}
      {isCondition && (
        <OutcomePickerPopover
          outcomeLabels={outcomeLabels}
          onPick={(label) => simulation.next(label)}
          onAutoEvaluate={() => simulation.autoEvaluate()}
        />
      )}

      {/* Auto-play toggle */}
      {!isCompleted && (
        <Button
          size="sm"
          variant={isAutoPlaying ? "destructive" : "ghost"}
          className="gap-1"
          onClick={handleAutoPlay}
        >
          {isAutoPlaying ? <Square className="h-3 w-3" /> : <FastForward className="h-3.5 w-3.5" />}
          {isAutoPlaying ? "Stop" : "Auto"}
        </Button>
      )}

      {/* Completed badge */}
      {isCompleted && (
        <Badge variant="outline" className="border-green-500 text-green-700">
          Completed
        </Badge>
      )}

      <div className="mx-1 h-4 border-l" />

      <Button size="sm" variant="ghost" className="gap-1" onClick={simulation.reset}>
        <RotateCcw className="h-3.5 w-3.5" />
        Restart
      </Button>

      <Button size="sm" variant="ghost" className="gap-1 text-red-500" onClick={simulation.stop}>
        <Square className="h-3.5 w-3.5" />
        Exit
      </Button>
    </div>
  );
}
