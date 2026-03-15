"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTelephonyConfig,
  updateTelephonyConfig,
  fetchPhoneNumbers,
  createPhoneNumber,
  updatePhoneNumber,
  deletePhoneNumber,
} from "@/lib/api";

export const settingsKeys = {
  telephony: ["settings", "telephony"] as const,
  phoneNumbers: ["settings", "phone-numbers"] as const,
};

export function useTelephonyConfig() {
  return useQuery({
    queryKey: settingsKeys.telephony,
    queryFn: fetchTelephonyConfig,
  });
}

export function useUpdateTelephonyConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, string>) => updateTelephonyConfig(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.telephony }),
  });
}

export function usePhoneNumbers() {
  return useQuery({
    queryKey: settingsKeys.phoneNumbers,
    queryFn: fetchPhoneNumbers,
  });
}

export function useCreatePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createPhoneNumber,
    onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.phoneNumbers }),
  });
}

export function useUpdatePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { label?: string; is_default?: boolean } }) =>
      updatePhoneNumber(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.phoneNumbers }),
  });
}

export function useDeletePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePhoneNumber(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.phoneNumbers }),
  });
}
