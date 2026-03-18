import { apiFetch } from "./api";

export interface MessagingProvider {
  id: string;
  provider_type: string;
  name: string;
  is_default: boolean;
  created_at: string;
}

export const fetchProviders = () =>
  apiFetch<MessagingProvider[]>("/api/messaging/providers");

export const createProvider = (data: { provider_type: string; name: string; credentials: Record<string, string>; is_default?: boolean }) =>
  apiFetch<MessagingProvider>("/api/messaging/providers", { method: "POST", body: JSON.stringify(data) });

export const updateProvider = (id: string, data: Partial<{ name: string; credentials: Record<string, string>; is_default: boolean }>) =>
  apiFetch<MessagingProvider>(`/api/messaging/providers/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteProvider = (id: string) =>
  apiFetch<void>(`/api/messaging/providers/${id}`, { method: "DELETE" });

export const testProvider = (id: string) =>
  apiFetch<{ success: boolean; message: string }>(`/api/messaging/providers/${id}/test`, { method: "POST" });
