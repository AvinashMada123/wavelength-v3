import { apiFetch } from "./api";

// --- Types ---
export interface SequenceTemplate {
  id: string;
  name: string;
  trigger_type: string;
  trigger_conditions: Record<string, any>;
  bot_id: string | null;
  max_active_per_lead: number;
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
