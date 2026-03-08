import type {
  BotConfig,
  CreateBotConfigRequest,
  UpdateBotConfigRequest,
  TriggerCallRequest,
  TriggerCallResponse,
  CallLog,
  QueuedCall,
  CircuitBreakerState,
  QueueStats,
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

export function fetchBot(id: string): Promise<BotConfig> {
  return apiFetch(`/api/bots/${id}`);
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

// --- Queue & Circuit Breaker ---

export function fetchQueuedCalls(params?: {
  bot_id?: string;
  status?: string;
  limit?: number;
}): Promise<QueuedCall[]> {
  const searchParams = new URLSearchParams();
  if (params?.bot_id) searchParams.set("bot_id", params.bot_id);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const qs = searchParams.toString();
  return apiFetch(`/api/queue${qs ? `?${qs}` : ""}`);
}

export function fetchQueueStats(): Promise<QueueStats[]> {
  return apiFetch("/api/queue/stats");
}

export function cancelQueuedCall(queueId: string): Promise<{ status: string }> {
  return apiFetch(`/api/queue/${queueId}/cancel`, { method: "POST" });
}

export function bulkCancelQueuedCalls(queueIds: string[]): Promise<{ cancelled: number }> {
  return apiFetch("/api/queue/bulk-cancel", {
    method: "POST",
    body: JSON.stringify(queueIds),
  });
}

export function bulkApproveHeldCalls(botId: string): Promise<{ status: string }> {
  return apiFetch(`/api/queue/bulk-approve?bot_id=${botId}`, {
    method: "POST",
  });
}

export function fetchCircuitBreakers(): Promise<CircuitBreakerState[]> {
  return apiFetch("/api/queue/circuit-breaker");
}

export function openCircuitBreaker(botId: string): Promise<{ status: string }> {
  return apiFetch(`/api/queue/circuit-breaker/${botId}/open`, {
    method: "POST",
  });
}

export function resetCircuitBreaker(botId: string): Promise<{ status: string }> {
  return apiFetch(`/api/queue/circuit-breaker/${botId}/reset`, {
    method: "POST",
  });
}
