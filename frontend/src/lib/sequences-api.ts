import { apiFetch } from "./api";

// --- Types ---
export interface TemplateVariable {
  key: string;
  default_value: string;
  description: string;
  type?: string;
}

export interface SequenceTemplate {
  id: string;
  name: string;
  trigger_type: string;
  trigger_conditions: Record<string, any>;
  bot_id: string | null;
  max_active_per_lead: number;
  variables: TemplateVariable[];
  is_active: boolean;
  step_count?: number;
  created_at: string;
}

export interface SequenceStep {
  id: string;
  template_id: string;
  step_order: number;
  name: string;
  is_active: boolean;
  channel: string;
  timing_type: string;
  timing_value: Record<string, any>;
  skip_conditions: Record<string, any> | null;
  content_type: string;
  whatsapp_template_name: string | null;
  whatsapp_template_params: any[] | null;
  ai_prompt: string | null;
  ai_model: string | null;
  voice_bot_id: string | null;
  expects_reply: boolean;
  reply_handler: Record<string, any> | null;
}

export interface SequenceInstance {
  id: string;
  template_id: string;
  template_name?: string;
  lead_id: string;
  lead_name?: string;
  lead_phone?: string;
  status: string;
  context_data: Record<string, any>;
  current_step?: number;
  next_touchpoint_at?: string;
  started_at: string;
  completed_at: string | null;
}

export interface SequenceTouchpoint {
  id: string;
  instance_id: string;
  step_order: number;
  step_snapshot: Record<string, any>;
  status: string;
  scheduled_at: string;
  generated_content: string | null;
  sent_at: string | null;
  reply_text: string | null;
  reply_response: string | null;
  error_message: string | null;
  retry_count: number;
}

export interface PromptTestResult {
  generated_content: string;
  tokens_used: number;
  latency_ms: number;
  cost_estimate: number;
  model: string;
  filled_prompt: string;
}

// --- Templates ---
export const fetchTemplates = (page = 1, pageSize = 50) =>
  apiFetch<{ items: SequenceTemplate[]; total: number }>(
    `/api/sequences/templates?page=${page}&page_size=${pageSize}`
  );

export const fetchTemplate = (id: string) =>
  apiFetch<SequenceTemplate & { steps: SequenceStep[] }>(`/api/sequences/templates/${id}`);

export const createTemplate = (data: Partial<SequenceTemplate>) =>
  apiFetch<SequenceTemplate>("/api/sequences/templates", { method: "POST", body: JSON.stringify(data) });

export const updateTemplate = (id: string, data: Partial<SequenceTemplate>) =>
  apiFetch<SequenceTemplate>(`/api/sequences/templates/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteTemplate = (id: string) =>
  apiFetch<void>(`/api/sequences/templates/${id}`, { method: "DELETE" });

// --- Steps ---
export const addStep = (templateId: string, data: Partial<SequenceStep>) =>
  apiFetch<SequenceStep>(`/api/sequences/templates/${templateId}/steps`, { method: "POST", body: JSON.stringify(data) });

export const updateStep = (stepId: string, data: Partial<SequenceStep>) =>
  apiFetch<SequenceStep>(`/api/sequences/steps/${stepId}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteStep = (stepId: string) =>
  apiFetch<void>(`/api/sequences/steps/${stepId}`, { method: "DELETE" });

export const reorderSteps = (templateId: string, stepIds: string[]) =>
  apiFetch<void>(`/api/sequences/templates/${templateId}/reorder`, { method: "POST", body: JSON.stringify({ step_ids: stepIds }) });

// --- Prompt Testing ---
export const testPrompt = (data: { prompt: string; variables: Record<string, string>; model?: string; max_tokens?: number }) =>
  apiFetch<PromptTestResult>("/api/sequences/test-prompt", { method: "POST", body: JSON.stringify(data) });

// --- Import/Export ---
export const exportTemplate = (id: string) =>
  apiFetch<Record<string, any>>(`/api/sequences/templates/${id}/export`);

export const importTemplate = (templateJson: Record<string, any>) =>
  apiFetch<SequenceTemplate>("/api/sequences/templates/import", { method: "POST", body: JSON.stringify(templateJson) });

export const previewImport = (templateJson: Record<string, any>) =>
  apiFetch<{ valid: boolean; errors: string[]; template: SequenceTemplate | null }>(
    "/api/sequences/templates/import/preview",
    { method: "POST", body: JSON.stringify(templateJson) }
  );

// --- Instances ---
export const fetchInstances = (params?: { lead_id?: string; template_id?: string; status?: string; page?: number }) => {
  const qs = new URLSearchParams();
  if (params?.lead_id) qs.set("lead_id", params.lead_id);
  if (params?.template_id) qs.set("template_id", params.template_id);
  if (params?.status) qs.set("status", params.status);
  if (params?.page) qs.set("page", String(params.page));
  return apiFetch<{ items: SequenceInstance[]; total: number }>(`/api/sequences/instances?${qs}`);
};

export const fetchInstance = (id: string) =>
  apiFetch<SequenceInstance & { touchpoints: SequenceTouchpoint[] }>(`/api/sequences/instances/${id}`);

export const pauseInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/pause`, { method: "POST" });

export const resumeInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/resume`, { method: "POST" });

export const cancelInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/cancel`, { method: "POST" });

// --- Touchpoints ---
export const fetchTouchpoint = (id: string) =>
  apiFetch<SequenceTouchpoint>(`/api/sequences/touchpoints/${id}`);

export const retryTouchpoint = (id: string) =>
  apiFetch<void>(`/api/sequences/touchpoints/${id}/retry`, { method: "POST" });

// --- Analytics Types ---
export interface AnalyticsFilters {
  start_date?: string;
  end_date?: string;
  template_id?: string;
  channel?: string;
  bot_id?: string;
}

export interface TrendData {
  sent_change: number | null;
  reply_rate_change: number | null;
  completion_rate_change: number | null;
  avg_reply_time_change: number | null;
}

export interface AnalyticsOverview {
  total_sent: number;
  total_failed: number;
  total_replied: number;
  reply_rate: number;
  completion_rate: number;
  avg_time_to_reply_hours: number | null;
  trend: TrendData;
}

export interface ChannelStats {
  channel: string;
  sent: number;
  failed: number;
  replied: number;
  reply_rate: number;
  percentage_of_total: number;
}

export interface FunnelStep {
  step_order: number;
  name: string;
  sent: number;
  skipped: number;
  failed: number;
  replied: number;
  drop_off_rate: number;
}

export interface FunnelData {
  template_name: string;
  total_entered: number;
  steps: FunnelStep[];
}

export interface TemplateStats {
  template_id: string;
  name: string;
  total_sent: number;
  completion_rate: number;
  reply_rate: number;
  avg_steps_completed: number;
  total_steps: number;
  active_instances: number;
  funnel_summary: number[];
}

export interface LeadStats {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string | null;
  score: number;
  tier: string;
  active_sequences: number;
  total_replies: number;
  last_interaction_at: string | null;
}

export interface TierSummary {
  hot: number;
  warm: number;
  cold: number;
  inactive: number;
}

export interface LeadsData {
  leads: LeadStats[];
  tier_summary: TierSummary;
  total: number;
  page: number;
  page_size: number;
}

export interface ScoreBreakdown {
  activity: { score: number; max: number };
  recency: { score: number; max: number };
  outcome: { score: number; max: number };
}

export interface TimelineEntry {
  timestamp: string;
  template_name: string;
  step_name: string;
  channel: string;
  status: string;
  content_preview: string | null;
  reply_text: string | null;
}

export interface LeadDetail {
  lead_id: string;
  lead_name: string | null;
  score: number;
  tier: string;
  score_breakdown: ScoreBreakdown;
  active_sequences: number;
  total_replies: number;
  avg_reply_time_hours: number | null;
  timeline: TimelineEntry[];
}

export interface FailureReason {
  reason: string;
  count: number;
}

export interface FailuresData {
  total_failed: number;
  reasons: FailureReason[];
  retry_stats: {
    total_retried: number;
    retry_success_rate: number;
  };
}

// --- Analytics ---
function buildAnalyticsQS(filters?: AnalyticsFilters): string {
  const qs = new URLSearchParams();
  if (filters?.start_date) qs.set("start_date", filters.start_date);
  if (filters?.end_date) qs.set("end_date", filters.end_date);
  if (filters?.template_id) qs.set("template_id", filters.template_id);
  if (filters?.channel) qs.set("channel", filters.channel);
  if (filters?.bot_id) qs.set("bot_id", filters.bot_id);
  return qs.toString();
}

export const fetchAnalyticsOverview = (filters?: AnalyticsFilters) =>
  apiFetch<AnalyticsOverview>(`/api/sequences/analytics/overview?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsChannels = (filters?: AnalyticsFilters) =>
  apiFetch<{ channels: ChannelStats[] }>(`/api/sequences/analytics/channels?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsTemplates = (filters?: AnalyticsFilters) =>
  apiFetch<{ templates: TemplateStats[] }>(`/api/sequences/analytics/templates?${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsFunnel = (templateId: string, filters?: AnalyticsFilters) =>
  apiFetch<FunnelData>(`/api/sequences/analytics/funnel?template_id=${templateId}&${buildAnalyticsQS(filters)}`);

export const fetchAnalyticsLeads = (
  filters?: AnalyticsFilters & { tier?: string; page?: number; page_size?: number; sort_by?: string; sort_order?: string }
) => {
  const qs = new URLSearchParams();
  if (filters?.start_date) qs.set("start_date", filters.start_date);
  if (filters?.end_date) qs.set("end_date", filters.end_date);
  if (filters?.template_id) qs.set("template_id", filters.template_id);
  if (filters?.channel) qs.set("channel", filters.channel);
  if (filters?.tier) qs.set("tier", filters.tier);
  if (filters?.page) qs.set("page", String(filters.page));
  if (filters?.page_size) qs.set("page_size", String(filters.page_size));
  if (filters?.sort_by) qs.set("sort_by", filters.sort_by);
  if (filters?.sort_order) qs.set("sort_order", filters.sort_order);
  return apiFetch<LeadsData>(`/api/sequences/analytics/leads?${qs}`);
};

export const fetchAnalyticsLeadDetail = (leadId: string) =>
  apiFetch<LeadDetail>(`/api/sequences/analytics/leads/${leadId}`);

export const fetchAnalyticsFailures = (filters?: AnalyticsFilters) =>
  apiFetch<FailuresData>(`/api/sequences/analytics/failures?${buildAnalyticsQS(filters)}`);
