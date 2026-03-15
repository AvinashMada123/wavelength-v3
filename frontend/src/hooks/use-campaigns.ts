"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCampaigns,
  getCampaign,
  createCampaign,
  startCampaign,
  pauseCampaign,
  cancelCampaign,
} from "@/lib/api";

export const campaignKeys = {
  all: ["campaigns"] as const,
  list: (filters: Record<string, string | number | undefined>) => ["campaigns", "list", filters] as const,
  detail: (id: string) => ["campaigns", id] as const,
};

export function useCampaigns(params?: {
  status?: string;
  page?: number;
  page_size?: number;
}) {
  return useQuery({
    queryKey: campaignKeys.list(params ?? {}),
    queryFn: () => fetchCampaigns(params),
  });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: campaignKeys.detail(id),
    queryFn: () => getCampaign(id),
    enabled: !!id,
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCampaign,
    onSuccess: () => qc.invalidateQueries({ queryKey: campaignKeys.all }),
  });
}

export function useStartCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => startCampaign(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: campaignKeys.all });
      qc.invalidateQueries({ queryKey: campaignKeys.detail(id) });
    },
  });
}

export function usePauseCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => pauseCampaign(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: campaignKeys.all });
      qc.invalidateQueries({ queryKey: campaignKeys.detail(id) });
    },
  });
}

export function useCancelCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => cancelCampaign(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: campaignKeys.all });
      qc.invalidateQueries({ queryKey: campaignKeys.detail(id) });
    },
  });
}
