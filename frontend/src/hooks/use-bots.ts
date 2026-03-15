"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchBots, fetchBot, createBot, updateBot, deleteBot, cloneBot } from "@/lib/api";
import type { CreateBotConfigRequest, UpdateBotConfigRequest } from "@/types/api";

export const botKeys = {
  all: ["bots"] as const,
  detail: (id: string) => ["bots", id] as const,
};

export function useBots() {
  return useQuery({
    queryKey: botKeys.all,
    queryFn: fetchBots,
  });
}

export function useBot(id: string) {
  return useQuery({
    queryKey: botKeys.detail(id),
    queryFn: () => fetchBot(id),
    enabled: !!id && id !== "new",
  });
}

export function useCreateBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateBotConfigRequest) => createBot(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: botKeys.all }),
  });
}

export function useUpdateBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateBotConfigRequest }) => updateBot(id, data),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: botKeys.all });
      qc.invalidateQueries({ queryKey: botKeys.detail(id) });
    },
  });
}

export function useDeleteBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteBot(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: botKeys.all }),
  });
}

export function useCloneBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => cloneBot(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: botKeys.all }),
  });
}
