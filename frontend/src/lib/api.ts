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

function extractErrorMessage(body: string, status: number): string {
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed.detail === "string") return parsed.detail;
    if (typeof parsed.message === "string") return parsed.message;
  } catch {
    // not JSON
  }
  return body || `Request failed (${status})`;
}

export async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
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
        throw new Error(extractErrorMessage(body, retryRes.status));
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
    throw new Error(extractErrorMessage(body, res.status));
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
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  return `/api/calls/${callSid}/recording${token ? `?token=${token}` : ""}`;
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
  params?: { outcome?: string; has_red_flags?: boolean; page?: number; page_size?: number; start_date?: string; end_date?: string }
): Promise<AnalyticsOutcomeItem[]> {
  const sp = new URLSearchParams();
  if (params?.outcome) sp.set("outcome", params.outcome);
  if (params?.has_red_flags !== undefined) sp.set("has_red_flags", String(params.has_red_flags));
  if (params?.page) sp.set("page", String(params.page));
  if (params?.page_size) sp.set("page_size", String(params.page_size));
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/${botId}/outcomes${qs ? `?${qs}` : ""}`);
}

export function fetchAnalyticsRedFlags(
  botId: string,
  params?: { severity?: string; flag_id?: string; start_date?: string; end_date?: string }
): Promise<RedFlagGroupItem[]> {
  const sp = new URLSearchParams();
  if (params?.severity) sp.set("severity", params.severity);
  if (params?.flag_id) sp.set("flag_id", params.flag_id);
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
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

export function acknowledgeAllAlerts(
  botId: string,
  acknowledgedBy: string
): Promise<{ status: string; count: number }> {
  return apiFetch(`/api/analytics/${botId}/alerts/acknowledge-all`, {
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
  params?: { interval?: "hourly" | "daily" | "weekly"; start_date?: string; end_date?: string }
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

// --- Leads ---

export interface Lead {
  id: string;
  org_id: string;
  phone_number: string;
  contact_name: string;
  email: string | null;
  company: string | null;
  location: string | null;
  tags: any[];
  custom_fields: Record<string, any>;
  status: string;
  qualification_level: string | null;
  qualification_confidence: number | null;
  call_count: number;
  last_call_date: string | null;
  source: string;
  ghl_contact_id: string | null;
  bot_notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaginatedLeads {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
}

export function fetchLeads(params?: {
  status?: string;
  search?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedLeads> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.search) sp.set("search", params.search);
  if (params?.page) sp.set("page", String(params.page));
  if (params?.page_size) sp.set("page_size", String(params.page_size));
  const qs = sp.toString();
  return apiFetch(`/api/leads${qs ? `?${qs}` : ""}`);
}

export function createLead(data: {
  phone_number: string;
  contact_name: string;
  email?: string;
  company?: string;
  location?: string;
  source?: string;
}): Promise<Lead> {
  return apiFetch("/api/leads", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateLead(id: string, data: Record<string, any>): Promise<Lead> {
  return apiFetch(`/api/leads/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function fetchLead(id: string): Promise<Lead> {
  return apiFetch(`/api/leads/${id}`);
}

export function fetchLeadCalls(leadId: string): Promise<CallLog[]> {
  return apiFetch(`/api/leads/${leadId}/calls`);
}

export function deleteLead(id: string): Promise<void> {
  return apiFetch(`/api/leads/${id}`, { method: "DELETE" });
}

// --- Campaigns ---

export interface Campaign {
  id: string;
  org_id: string;
  bot_config_id: string;
  name: string;
  status: string;
  total_leads: number;
  completed_leads: number;
  failed_leads: number;
  concurrency_limit: number;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  lead_status_breakdown?: Record<string, number>;
}

export interface PaginatedCampaigns {
  items: Campaign[];
  total: number;
  page: number;
  page_size: number;
}

export function fetchCampaigns(params?: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedCampaigns> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.page) sp.set("page", String(params.page));
  if (params?.page_size) sp.set("page_size", String(params.page_size));
  const qs = sp.toString();
  return apiFetch(`/api/campaigns${qs ? `?${qs}` : ""}`);
}

export function createCampaign(data: {
  name: string;
  bot_config_id: string;
  lead_ids: string[];
  concurrency_limit?: number;
}): Promise<Campaign> {
  return apiFetch("/api/campaigns", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getCampaign(id: string): Promise<Campaign> {
  return apiFetch(`/api/campaigns/${id}`);
}

export function startCampaign(id: string): Promise<Campaign> {
  return apiFetch(`/api/campaigns/${id}/start`, { method: "POST" });
}

export function pauseCampaign(id: string): Promise<Campaign> {
  return apiFetch(`/api/campaigns/${id}/pause`, { method: "POST" });
}

export function cancelCampaign(id: string): Promise<Campaign> {
  return apiFetch(`/api/campaigns/${id}/cancel`, { method: "POST" });
}

// --- Admin ---

export interface OrgSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
  user_count: number;
  bot_count: number;
  call_count: number;
  created_at: string;
}

export interface AdminStats {
  total_orgs: number;
  total_users: number;
  total_bots: number;
  total_calls: number;
  calls_today: number;
  calls_by_status: Array<{ status: string; count: number }>;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  org_id: string;
  org_name: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
}

export function fetchAdminStats(): Promise<AdminStats> {
  return apiFetch("/api/admin/stats");
}

export function fetchAdminOrgs(): Promise<OrgSummary[]> {
  return apiFetch("/api/admin/organizations");
}

export function fetchAdminOrgDetail(orgId: string): Promise<any> {
  return apiFetch(`/api/admin/organizations/${orgId}`);
}

export function fetchAdminUsers(orgId?: string): Promise<AdminUser[]> {
  const qs = orgId ? `?org_id=${orgId}` : "";
  return apiFetch(`/api/admin/users${qs}`);
}

export function createAdminOrg(data: { name: string; plan?: string }): Promise<any> {
  return apiFetch("/api/admin/organizations", { method: "POST", body: JSON.stringify(data) });
}

export function createAdminUser(data: { email: string; display_name: string; password: string; role: string; org_id: string }): Promise<any> {
  return apiFetch("/api/admin/users", { method: "POST", body: JSON.stringify(data) });
}

export function updateAdminUser(userId: string, data: { email?: string; password?: string; display_name?: string; role?: string }): Promise<AdminUser> {
  return apiFetch(`/api/admin/users/${userId}`, { method: "PUT", body: JSON.stringify(data) });
}

export function impersonateUser(userId: string): Promise<{ access_token: string; refresh_token: string }> {
  return apiFetch(`/api/admin/impersonate/${userId}`, { method: "POST" });
}

export interface OrgSettings {
  org_id: string;
  org_name: string;
  max_concurrent_calls: number;
}

export function fetchOrgSettings(orgId: string): Promise<OrgSettings> {
  return apiFetch(`/api/admin/organizations/${orgId}/settings`);
}

export function updateOrgSettings(orgId: string, data: { max_concurrent_calls?: number }): Promise<OrgSettings> {
  return apiFetch(`/api/admin/organizations/${orgId}/settings`, { method: "PATCH", body: JSON.stringify(data) });
}

// --- Billing ---

export interface CreditTransaction {
  id: string;
  org_id: string;
  amount: number;
  balance_after: number;
  type: string; // "topup", "usage", "adjustment", "refund"
  description: string;
  reference_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface PaginatedTransactions {
  items: CreditTransaction[];
  total: number;
  page: number;
  page_size: number;
}

export function fetchCreditBalance(): Promise<{ balance: number; org_id: string }> {
  return apiFetch("/api/billing/balance");
}

export function fetchCreditTransactions(params?: { page?: number; page_size?: number; type?: string }): Promise<PaginatedTransactions> {
  const sp = new URLSearchParams();
  if (params?.page) sp.set("page", String(params.page));
  if (params?.page_size) sp.set("page_size", String(params.page_size));
  if (params?.type) sp.set("type", params.type);
  const qs = sp.toString();
  return apiFetch(`/api/billing/transactions${qs ? `?${qs}` : ""}`);
}

// Payments (Cashfree)
export function createPaymentOrder(credits: number, phone?: string): Promise<{
  order_id: string;
  payment_session_id: string;
  amount: number;
  cf_environment: string;
}> {
  return apiFetch("/api/payments/create-order", {
    method: "POST",
    body: JSON.stringify({ credits, phone: phone || "9999999999" }),
  });
}

export function verifyPayment(orderId: string): Promise<{
  order_id: string;
  status: string;
  credits: number;
  amount: number;
}> {
  return apiFetch(`/api/payments/verify/${orderId}`);
}

// Admin billing
export function addCredits(orgId: string, amount: number, description?: string): Promise<{ balance: number }> {
  return apiFetch("/api/billing/admin/add-credits", {
    method: "POST",
    body: JSON.stringify({ org_id: orgId, amount, description }),
  });
}

export function fetchOrgBalances(): Promise<Array<{ org_id: string; org_name: string; credit_balance: number }>> {
  return apiFetch("/api/billing/admin/org-balances");
}

// --- Org Switching ---

export interface OrgMembership {
  org_id: string;
  org_name: string;
  org_slug: string;
  role: string;
  is_active: boolean;
}

export function fetchUserOrgs(): Promise<OrgMembership[]> {
  return apiFetch("/api/auth/orgs");
}

export function switchOrg(orgId: string): Promise<{ access_token: string; refresh_token: string; user: { id: string; email: string; display_name: string; role: string; org_id: string; org_name: string } }> {
  return apiFetch("/api/auth/switch-org", {
    method: "POST",
    body: JSON.stringify({ org_id: orgId }),
  });
}

// --- Telephony Config ---

export interface TelephonyConfig {
  plivo_auth_id: string | null;
  plivo_auth_token_set: boolean;
  twilio_account_sid: string | null;
  twilio_auth_token_set: boolean;
  ghl_api_key_set: boolean;
  ghl_location_id: string | null;
}

export interface PhoneNumberEntry {
  id: string;
  provider: string;
  phone_number: string;
  label: string | null;
  is_default: boolean;
}

export function fetchTelephonyConfig(): Promise<TelephonyConfig> {
  return apiFetch("/api/telephony/config");
}

export function updateTelephonyConfig(data: Record<string, string>): Promise<TelephonyConfig> {
  return apiFetch("/api/telephony/config", { method: "PATCH", body: JSON.stringify(data) });
}

export function fetchPhoneNumbers(): Promise<PhoneNumberEntry[]> {
  return apiFetch("/api/telephony/phone-numbers");
}

export function createPhoneNumber(data: { provider: string; phone_number: string; label?: string; is_default?: boolean }): Promise<PhoneNumberEntry> {
  return apiFetch("/api/telephony/phone-numbers", { method: "POST", body: JSON.stringify(data) });
}

export function updatePhoneNumber(id: string, data: { label?: string; is_default?: boolean }): Promise<PhoneNumberEntry> {
  return apiFetch(`/api/telephony/phone-numbers/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export function deletePhoneNumber(id: string): Promise<void> {
  return apiFetch(`/api/telephony/phone-numbers/${id}`, { method: "DELETE" });
}

// --- Dashboard Analytics ---

export interface DashboardAnalytics {
  total_calls: number;
  connected_pct: number;
  avg_duration_secs: number;
  conversion_pct: number;
  total_cost: number;
  cost_per_conversion: number;
  call_volume_by_day: Array<{ date: string; count: number }>;
  outcome_distribution: Record<string, number>;
  sentiment_distribution: Record<string, number>;
  top_objections: Array<{ label: string; count: number }>;
  calling_heatmap: Array<{ hour: number; day: number; count: number }>;
  conversion_funnel: Array<{ stage: string; count: number; percentage: number }>;
}

export function fetchDashboardAnalytics(params?: {
  bot_id?: string;
  days?: number;
}): Promise<DashboardAnalytics> {
  const sp = new URLSearchParams();
  if (params?.bot_id) sp.set("bot_id", params.bot_id);
  if (params?.days) sp.set("days", String(params.days));
  const qs = sp.toString();
  return apiFetch(`/api/analytics/dashboard${qs ? `?${qs}` : ""}`);
}

export interface CostBreakdown {
  total_cost: number;
  cost_per_call: number;
  cost_per_conversion: number;
  cost_by_type: Record<string, number>;
  daily_costs: Array<{ date: string; cost: number }>;
}

export function fetchCostBreakdown(params?: {
  bot_id?: string;
  days?: number;
  start_date?: string;
  end_date?: string;
}): Promise<CostBreakdown> {
  const sp = new URLSearchParams();
  if (params?.bot_id) sp.set("bot_id", params.bot_id);
  if (params?.days) sp.set("days", String(params.days));
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/cost-breakdown${qs ? `?${qs}` : ""}`);
}

// --- Lead Intelligence ---

export interface LeadIntelligence {
  temperature_distribution: Record<string, number>;
  buying_signals: Array<{ signal: string; count: number }>;
  total_analyzed: number;
}

export function fetchLeadIntelligence(params?: {
  bot_id?: string;
  days?: number;
  start_date?: string;
  end_date?: string;
}): Promise<LeadIntelligence> {
  const sp = new URLSearchParams();
  if (params?.bot_id) sp.set("bot_id", params.bot_id);
  if (params?.days) sp.set("days", String(params.days));
  if (params?.start_date) sp.set("start_date", params.start_date);
  if (params?.end_date) sp.set("end_date", params.end_date);
  const qs = sp.toString();
  return apiFetch(`/api/analytics/lead-intelligence${qs ? `?${qs}` : ""}`);
}

// --- Reanalysis ---

export interface ReanalysisResult {
  total_eligible: number;
  processed: number;
  succeeded: number;
  failed: number;
  errors: string[];
}

export function reanalyzeCalls(params?: {
  bot_id?: string;
  limit?: number;
  force?: boolean;
}): Promise<ReanalysisResult> {
  const sp = new URLSearchParams();
  if (params?.bot_id) sp.set("bot_id", params.bot_id);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.force) sp.set("force", "true");
  const qs = sp.toString();
  return apiFetch(`/api/analytics/reanalyze${qs ? `?${qs}` : ""}`, { method: "POST" });
}
