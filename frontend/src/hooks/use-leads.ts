"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchLeads, fetchLead, createLead, updateLead, deleteLead } from "@/lib/api";

export const leadKeys = {
  all: ["leads"] as const,
  list: (filters: Record<string, string | number | undefined>) => ["leads", "list", filters] as const,
  detail: (id: string) => ["leads", id] as const,
};

export function useLeads(params?: {
  status?: string;
  search?: string;
  page?: number;
  page_size?: number;
}) {
  return useQuery({
    queryKey: leadKeys.list(params ?? {}),
    queryFn: () => fetchLeads(params),
  });
}

export function useLead(id: string) {
  return useQuery({
    queryKey: leadKeys.detail(id),
    queryFn: () => fetchLead(id),
    enabled: !!id,
  });
}

export function useCreateLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createLead,
    onSuccess: () => qc.invalidateQueries({ queryKey: leadKeys.all }),
  });
}

export function useUpdateLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, any> }) => updateLead(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: leadKeys.all }),
  });
}

export function useDeleteLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteLead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: leadKeys.all }),
  });
}
