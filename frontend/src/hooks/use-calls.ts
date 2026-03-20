"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCallLogs,
  fetchCallDetail,
  exportCallLogs,
  triggerCall,
  checkHealth,
} from "@/lib/api";
import type { TriggerCallRequest } from "@/types/api";

export const callKeys = {
  all: ["calls"] as const,
  list: (filters: Record<string, string | undefined>) => ["calls", "list", filters] as const,
  detail: (id: string) => ["calls", id] as const,
  health: ["health"] as const,
};

export function useCallLogs(filters?: { botId?: string; goalOutcome?: string }) {
  return useQuery({
    queryKey: callKeys.list(filters ?? {}),
    queryFn: () => fetchCallLogs(filters),
  });
}

export function useCallDetail(callId: string) {
  return useQuery({
    queryKey: callKeys.detail(callId),
    queryFn: () => fetchCallDetail(callId),
    enabled: !!callId,
  });
}

export function useExportCallLogs() {
  return useMutation({
    mutationFn: (filters?: { botId?: string; goalOutcome?: string }) =>
      exportCallLogs(filters?.botId, filters?.goalOutcome),
  });
}

export function useTriggerCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TriggerCallRequest) => triggerCall(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: callKeys.all });
    },
  });
}

export function useHealthCheck() {
  return useQuery({
    queryKey: callKeys.health,
    queryFn: checkHealth,
    staleTime: 10 * 1000,
    refetchInterval: 30 * 1000,
  });
}
