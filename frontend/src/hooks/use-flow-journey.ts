"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchFlowInstances,
  fetchJourneyData,
  type FlowInstanceSummary,
  type JourneyData,
} from "@/lib/flows-api";

export interface UseFlowJourneyReturn {
  // Instance list
  instances: FlowInstanceSummary[];
  total: number;
  loading: boolean;
  // Filters
  statusFilter: string | null;
  setStatusFilter: (status: string | null) => void;
  // Selection
  selectedInstanceId: string | null;
  selectInstance: (id: string) => void;
  clearSelection: () => void;
  // Journey data
  journeyData: JourneyData | null;
  journeyLoading: boolean;
  // Derived canvas highlighting data
  visitedNodeIds: string[];
  visitedEdgeIds: string[];
  errorNodeIds: string[];
  currentNodeId: string | null;
  /** Map from node_id → touchpoint data for overlay display */
  touchpointByNode: Map<string, JourneyData["touchpoints"][0]>;
  /** Map from edge_id → transition data for elapsed time display */
  transitionByEdge: Map<string, JourneyData["transitions"][0]>;
  // Refresh
  refresh: () => void;
}

export function useFlowJourney(flowId: string): UseFlowJourneyReturn {
  const [instances, setInstances] = useState<FlowInstanceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [journeyData, setJourneyData] = useState<JourneyData | null>(null);
  const [journeyLoading, setJourneyLoading] = useState(false);

  // Load instances
  const loadInstances = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchFlowInstances(flowId, {
        status: statusFilter ?? undefined,
        limit: 50,
      });
      setInstances(result.instances);
      setTotal(result.total);
    } catch {
      // Silently fail — will show empty list
    } finally {
      setLoading(false);
    }
  }, [flowId, statusFilter]);

  useEffect(() => {
    loadInstances();
  }, [loadInstances]);

  // Load journey when instance selected
  const selectInstance = useCallback(async (id: string) => {
    setSelectedInstanceId(id);
    setJourneyLoading(true);
    try {
      const data = await fetchJourneyData(flowId, id);
      setJourneyData(data);
    } catch {
      setJourneyData(null);
    } finally {
      setJourneyLoading(false);
    }
  }, [flowId]);

  const clearSelection = useCallback(() => {
    setSelectedInstanceId(null);
    setJourneyData(null);
  }, []);

  // Derive highlighting data from journey
  const visitedNodeIds = journeyData
    ? journeyData.touchpoints.map((tp) => tp.node_id)
    : [];

  const visitedEdgeIds = journeyData
    ? journeyData.transitions
        .filter((t) => t.edge_id)
        .map((t) => t.edge_id!)
    : [];

  const errorNodeIds = journeyData
    ? journeyData.touchpoints
        .filter((tp) => tp.status === "failed")
        .map((tp) => tp.node_id)
    : [];

  const currentNodeId = journeyData?.instance.current_node_id ?? null;

  const touchpointByNode = new Map(
    (journeyData?.touchpoints ?? []).map((tp) => [tp.node_id, tp]),
  );

  const transitionByEdge = new Map(
    (journeyData?.transitions ?? [])
      .filter((t) => t.edge_id)
      .map((t) => [t.edge_id!, t]),
  );

  return {
    instances,
    total,
    loading,
    statusFilter,
    setStatusFilter,
    selectedInstanceId,
    selectInstance,
    clearSelection,
    journeyData,
    journeyLoading,
    visitedNodeIds,
    visitedEdgeIds,
    errorNodeIds,
    currentNodeId,
    touchpointByNode,
    transitionByEdge,
    refresh: loadInstances,
  };
}
