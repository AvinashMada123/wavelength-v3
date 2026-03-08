export interface GHLWorkflow {
  id: string;
  name: string;
  tag: string;
  timing: "pre_call" | "during_call" | "post_call";
  enabled: boolean;
  trigger_description?: string;
}

export interface BotConfig {
  id: string;
  agent_name: string;
  company_name: string;
  location: string | null;
  event_name: string | null;
  event_date: string | null;
  event_time: string | null;
  tts_provider: "gemini" | "sarvam";
  tts_voice: string;
  tts_style_prompt: string | null;
  language: string;
  system_prompt_template: string;
  context_variables: Record<string, string>;
  silence_timeout_secs: number;
  ghl_webhook_url: string | null;
  ghl_api_key: string | null;
  ghl_location_id: string | null;
  ghl_post_call_tag: string | null;
  ghl_workflows: GHLWorkflow[];
  max_call_duration: number;
  telephony_provider: "plivo" | "twilio";
  plivo_caller_id: string;
  twilio_phone_number: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateBotConfigRequest {
  agent_name: string;
  company_name: string;
  location?: string | null;
  event_name?: string | null;
  event_date?: string | null;
  event_time?: string | null;
  tts_provider?: "gemini" | "sarvam";
  tts_voice?: string;
  tts_style_prompt?: string | null;
  language?: string;
  system_prompt_template: string;
  context_variables?: Record<string, string>;
  silence_timeout_secs?: number;
  ghl_webhook_url?: string | null;
  ghl_api_key?: string | null;
  ghl_location_id?: string | null;
  ghl_post_call_tag?: string | null;
  ghl_workflows?: GHLWorkflow[];
  max_call_duration?: number;
  telephony_provider?: "plivo" | "twilio";
  plivo_auth_id?: string;
  plivo_auth_token?: string;
  plivo_caller_id?: string;
  twilio_account_sid?: string | null;
  twilio_auth_token?: string | null;
  twilio_phone_number?: string | null;
}

export interface UpdateBotConfigRequest {
  agent_name?: string | null;
  company_name?: string | null;
  location?: string | null;
  event_name?: string | null;
  event_date?: string | null;
  event_time?: string | null;
  tts_provider?: "gemini" | "sarvam" | null;
  tts_voice?: string | null;
  tts_style_prompt?: string | null;
  language?: string | null;
  system_prompt_template?: string | null;
  context_variables?: Record<string, string> | null;
  silence_timeout_secs?: number | null;
  ghl_webhook_url?: string | null;
  ghl_api_key?: string | null;
  ghl_location_id?: string | null;
  ghl_post_call_tag?: string | null;
  ghl_workflows?: GHLWorkflow[] | null;
  max_call_duration?: number | null;
  telephony_provider?: "plivo" | "twilio" | null;
  plivo_auth_id?: string | null;
  plivo_auth_token?: string | null;
  plivo_caller_id?: string | null;
  twilio_account_sid?: string | null;
  twilio_auth_token?: string | null;
  twilio_phone_number?: string | null;
  is_active?: boolean | null;
}

export interface TriggerCallRequest {
  bot_id: string;
  contact_name: string;
  contact_phone: string;
  ghl_contact_id?: string | null;
  extra_vars?: Record<string, string>;
}

export interface TriggerCallResponse {
  queue_id: string;
  status: string;
}

export interface QueuedCall {
  id: string;
  bot_id: string;
  contact_name: string;
  contact_phone: string;
  ghl_contact_id: string | null;
  extra_vars: Record<string, string>;
  source: string;
  status: "queued" | "processing" | "completed" | "failed" | "held" | "cancelled";
  priority: number;
  error_message: string | null;
  call_log_id: string | null;
  created_at: string;
  processed_at: string | null;
  bot_name: string | null;
}

export interface CircuitBreakerState {
  bot_id: string;
  bot_name: string | null;
  state: "closed" | "open";
  consecutive_failures: number;
  failure_threshold: number;
  last_failure_at: string | null;
  last_failure_reason: string | null;
  opened_at: string | null;
  opened_by: string | null;
  updated_at: string;
}

export interface QueueStats {
  bot_id: string;
  bot_name: string;
  queued: number;
  held: number;
  processing: number;
  completed: number;
  failed: number;
  cancelled: number;
}

export interface CallLogMetadata {
  transcript?: Array<{ role: "user" | "assistant"; content: string }>;
  interest_level?: "high" | "medium" | "low";
  recording_url?: string;
  call_metrics?: { turn_count: number; total_duration_s?: number };
}

export interface CallLog {
  id: string;
  bot_id: string;
  call_sid: string;
  contact_name: string;
  contact_phone: string;
  ghl_contact_id: string | null;
  status: string;
  outcome: string | null;
  call_duration: number | null;
  summary: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  metadata?: CallLogMetadata | null;
}
