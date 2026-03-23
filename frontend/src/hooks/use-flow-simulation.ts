"use client";

import { useState, useCallback, useRef } from "react";
import {
  SimulationEngine,
  type FlowGraph,
  type MockLead,
  type SimulationState,
  type ActionPreview,
  type JourneySummary,
} from "@/lib/flow-simulation";

export interface UseFlowSimulationReturn {
  isActive: boolean;
  simulationState: SimulationState | null;
  actionPreview: ActionPreview | null;
  journeySummary: JourneySummary | null;
  start: (lead: MockLead) => void;
  stop: () => void;
  next: (outcomeLabel: string) => void;
  autoEvaluate: () => { resolvedLabel: string } | null;
  autoPlay: (intervalMs?: number) => void;
  stopAutoPlay: () => void;
  reset: () => void;
}

export function useFlowSimulation(graph: FlowGraph): UseFlowSimulationReturn {
  const [isActive, setIsActive] = useState(false);
  const [simulationState, setSimulationState] = useState<SimulationState | null>(null);
  const [actionPreview, setActionPreview] = useState<ActionPreview | null>(null);
  const [journeySummary, setJourneySummary] = useState<JourneySummary | null>(null);
  const engineRef = useRef<SimulationEngine | null>(null);
  const autoPlayRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const updateState = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const state = engine.getState();
    setSimulationState(state);
    setJourneySummary(engine.getJourneySummary());
    if (state.status === "active") {
      setActionPreview(engine.getActionPreview());
    } else {
      setActionPreview(null);
    }
  }, []);

  const start = useCallback((lead: MockLead) => {
    const engine = new SimulationEngine(graph, lead);
    engineRef.current = engine;
    setIsActive(true);
    updateState();
  }, [graph, updateState]);

  const stop = useCallback(() => {
    if (autoPlayRef.current) {
      clearInterval(autoPlayRef.current);
      autoPlayRef.current = null;
    }
    engineRef.current = null;
    setIsActive(false);
    setSimulationState(null);
    setActionPreview(null);
    setJourneySummary(null);
  }, []);

  const next = useCallback((outcomeLabel: string) => {
    engineRef.current?.advance(outcomeLabel);
    updateState();
  }, [updateState]);

  const autoEvaluate = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return null;
    const result = engine.autoEvaluate();
    updateState();
    return { resolvedLabel: result.resolvedLabel };
  }, [updateState]);

  const autoPlay = useCallback((intervalMs = 1000) => {
    if (autoPlayRef.current) clearInterval(autoPlayRef.current);
    autoPlayRef.current = setInterval(() => {
      const engine = engineRef.current;
      if (!engine) return;
      const state = engine.getState();
      if (state.status === "completed") {
        if (autoPlayRef.current) clearInterval(autoPlayRef.current);
        autoPlayRef.current = null;
        return;
      }
      const currentNode = graph.nodes.find((n) => n.id === state.currentNodeId);
      if (currentNode?.type === "condition") {
        engine.autoEvaluate();
      } else {
        engine.advance("default");
      }
      updateState();
    }, intervalMs);
  }, [graph, updateState]);

  const stopAutoPlay = useCallback(() => {
    if (autoPlayRef.current) {
      clearInterval(autoPlayRef.current);
      autoPlayRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    engineRef.current?.reset();
    updateState();
  }, [updateState]);

  return {
    isActive,
    simulationState,
    actionPreview,
    journeySummary,
    start,
    stop,
    next,
    autoEvaluate,
    autoPlay,
    stopAutoPlay,
    reset,
  };
}
