import type {
  BotConfig,
  CreateBotConfigRequest,
  UpdateBotConfigRequest,
  TriggerCallRequest,
  TriggerCallResponse,
  CallLog,
} from "@/types/api";

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export function fetchBots(): Promise<BotConfig[]> {
  return apiFetch("/api/bots");
}

export function createBot(data: CreateBotConfigRequest): Promise<BotConfig> {
  return apiFetch("/api/bots", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateBot(id: string, data: UpdateBotConfigRequest): Promise<BotConfig> {
  return apiFetch(`/api/bots/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteBot(id: string): Promise<void> {
  return apiFetch(`/api/bots/${id}`, { method: "DELETE" });
}

export function triggerCall(data: TriggerCallRequest): Promise<TriggerCallResponse> {
  return apiFetch("/api/calls/trigger", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function fetchCallLogs(botId?: string): Promise<CallLog[]> {
  const params = botId ? `?bot_id=${botId}` : "";
  return apiFetch(`/api/calls${params}`);
}

export async function checkHealth(): Promise<{ status: string }> {
  return apiFetch("/health");
}

export function getRecordingUrl(callSid: string): string {
  return `/api/calls/${callSid}/recording`;
}
