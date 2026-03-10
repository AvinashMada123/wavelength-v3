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
  AnalyticsSummaryResponse,
  AnalyticsOutcomeItem,
  RedFlagGroupItem,
  AlertsResponse,
  TrendPoint,
  CapturedDataFieldSummary,
} from "@/types/api";

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) return false;
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token", data.access_token);
    return true;
  } catch {
    return false;
  }
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    // Token expired — try refresh
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      headers["Authorization"] = `Bearer ${localStorage.getItem("access_token")}`;
      const retryRes = await fetch(url, { ...options, headers });
      if (!retryRes.ok) {
        const body = await retryRes.text();
        throw new Error(`${retryRes.status}: ${body}`);
      }
      return retryRes.json();
    }
    // Refresh failed — redirect to login
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("auth_user");
      window.location.href = "/login";
    }
    throw new Error("Authentication expired");
  }

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

export function cloneBot(id: string): Promise<BotConfig> {
  return apiFetch(`/api/bots/${id}/clone`, { method: "POST" });
}

export function triggerCall(data: TriggerCallRequest): Promise<TriggerCallResponse> {
  return apiFetch("/api/calls/trigger", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function fetchCallLogs(botId?: string, goalOutcome?: string): Promise<CallLog[]> {
  const sp = new URLSearchParams();
  if (botId) sp.set("bot_id", botId);
  if (goalOutcome) sp.set("goal_outcome", goalOutcome);
  const qs = sp.toString();
  return apiFetch(`/api/calls${qs ? `?${qs}` : ""}`);
}

export function fetchCallDetail(callId: string): Promise<CallLog> {
  return apiFetch(`/api/calls/${callId}`);
}

export function exportCallLogs(botId?: string, goalOutcome?: string): Promise<CallLog[]> {
  const sp = new URLSearchParams();
  if (botId) sp.set("bot_id", botId);
  if (goalOutcome) sp.set("goal_outcome", goalOutcome);
  const qs = sp.toString();
  return apiFetch(`/api/calls/export${qs ? `?${qs}` : ""}`);
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

export function triggerQueuedCall(queueId: string): Promise<{ status: string }> {
  return apiFetch(`/api/queue/${queueId}/trigger`, { method: "POST" });
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

// --- Analytics ---

export function fetchAnalyticsSummary(
  botId: string,
  params?: { start_date?: string; end_date?: string }
): Promise<AnalyticsSummaryResponse> {
  const sp = new URLSearchParams();
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/summary${qs ? `?${qs}` : ""}`);
}

export function fetchAnalyticsOutcomes(
  botId: string,
  params?: { outcome?: string; has_red_flags?: boolean; page?: number; page_size?: number }
): Promise<AnalyticsOutcomeItem[]> {
  const sp = new URLSearchParams();
  if (params?.outcome) sp.set("outcome", params.outcome);
  if (params?.has_red_flags !== undefined) sp.set("has_red_flags", String(params.has_red_flags));
  if (params?.page) sp.set("page", String(params.page));
  if (params?.page_size) sp.set("page_size", String(params.page_size));
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/outcomes${qs ? `?${qs}` : ""}`);
}

export function fetchAnalyticsRedFlags(
  botId: string,
  params?: { severity?: string; flag_id?: string }
): Promise<RedFlagGroupItem[]> {
  const sp = new URLSearchParams();
  if (params?.severity) sp.set("severity", params.severity);
  if (params?.flag_id) sp.set("flag_id", params.flag_id);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/red-flags${qs ? `?${qs}` : ""}`);
}

export function fetchAnalyticsAlerts(botId: string): Promise<AlertsResponse> {
  return apiFetch(`/api/analytics/${botId}/alerts`);
}

export function acknowledgeAlert(
  botId: string,
  analyticsId: string,
  acknowledgedBy: string
): Promise<{ status: string }> {
  return apiFetch(`/api/analytics/${botId}/alerts/${analyticsId}/acknowledge`, {
    method: "POST",
    body: JSON.stringify({ acknowledged_by: acknowledgedBy }),
  });
}

export function snoozeAlert(
  botId: string,
  analyticsId: string,
  snoozeUntil: string
): Promise<{ status: string }> {
  return apiFetch(`/api/analytics/${botId}/alerts/${analyticsId}/snooze`, {
    method: "POST",
    body: JSON.stringify({ snooze_until: snoozeUntil }),
  });
}

export function fetchAnalyticsTrends(
  botId: string,
  params?: { interval?: "daily" | "weekly"; start_date?: string; end_date?: string }
): Promise<TrendPoint[]> {
  const sp = new URLSearchParams();
  if (params?.interval) sp.set("interval", params.interval);
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/trends${qs ? `?${qs}` : ""}`);
}

export function fetchAnalyticsCapturedData(
  botId: string,
  params?: { start_date?: string; end_date?: string }
): Promise<CapturedDataFieldSummary[]> {
  const sp = new URLSearchParams();
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/captured-data${qs ? `?${qs}` : ""}`);
}

// --- Auth & Team ---

export interface Invite {
  id: string;
  email: string;
  org_id: string;
  org_name: string;
  role: string;
  status: string;
  created_at: string;
  expires_at: string;
}

export function fetchInvites(): Promise<Invite[]> {
  return apiFetch("/api/auth/invites");
}

export function createInvite(email: string, role: string = "client_user"): Promise<Invite> {
  return apiFetch("/api/auth/invite", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}
