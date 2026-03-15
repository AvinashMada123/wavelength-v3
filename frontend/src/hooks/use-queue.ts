"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchQueuedCalls,
  fetchQueueStats,
  fetchCircuitBreakers,
  cancelQueuedCall,
  triggerQueuedCall,
  bulkCancelQueuedCalls,
  bulkApproveHeldCalls,
  openCircuitBreaker,
  resetCircuitBreaker,
} from "@/lib/api";

export const queueKeys = {
  all: ["queue"] as const,
  list: (filters: Record<string, string | number | undefined>) => ["queue", "list", filters] as const,
  stats: ["queue", "stats"] as const,
  circuitBreakers: ["queue", "circuit-breakers"] as const,
};

export function useQueuedCalls(params?: {
  bot_id?: string;
  status?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: queueKeys.list(params ?? {}),
    queryFn: () => fetchQueuedCalls(params),
    refetchInterval: 5 * 1000,
  });
}

export function useQueueStats() {
  return useQuery({
    queryKey: queueKeys.stats,
    queryFn: fetchQueueStats,
    refetchInterval: 5 * 1000,
  });
}

export function useCircuitBreakers() {
  return useQuery({
    queryKey: queueKeys.circuitBreakers,
    queryFn: fetchCircuitBreakers,
    refetchInterval: 10 * 1000,
  });
}

export function useCancelQueuedCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (queueId: string) => cancelQueuedCall(queueId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.all }),
  });
}

export function useTriggerQueuedCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (queueId: string) => triggerQueuedCall(queueId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.all }),
  });
}

export function useBulkCancelQueuedCalls() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (queueIds: string[]) => bulkCancelQueuedCalls(queueIds),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.all }),
  });
}

export function useBulkApproveHeldCalls() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => bulkApproveHeldCalls(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.all }),
  });
}

export function useOpenCircuitBreaker() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => openCircuitBreaker(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.circuitBreakers }),
  });
}

export function useResetCircuitBreaker() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => resetCircuitBreaker(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queueKeys.circuitBreakers }),
  });
}
