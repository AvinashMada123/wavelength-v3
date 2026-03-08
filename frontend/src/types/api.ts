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
  goal_config: GoalConfig | null;
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
  goal_config?: GoalConfig | null;
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
  goal_config?: GoalConfig | null;
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

// --- Goal Config ---

export interface RedFlagConfig {
  id: string;
  label: string;
  severity: "critical" | "high" | "medium" | "low";
  auto_detect?: boolean;
  keywords?: string[];
  detect_in?: "realtime" | "post_call";
}

export interface SuccessCriterion {
  id: string;
  label: string;
  is_primary?: boolean;
}

export interface DataCaptureField {
  id: string;
  label: string;
  type: "string" | "integer" | "float" | "boolean" | "enum";
  enum_values?: string[];
  description?: string;
}

export interface GoalConfig {
  version?: number;
  goal_type: string;
  goal_description: string;
  success_criteria: SuccessCriterion[];
  red_flags?: RedFlagConfig[];
  data_capture_fields?: DataCaptureField[];
}

// --- Analytics ---

export interface OutcomeSummary {
  outcome: string;
  count: number;
  percentage: number;
}

export interface AnalyticsSummaryResponse {
  bot_id: string;
  total_analyzed: number;
  outcomes: OutcomeSummary[];
  avg_duration_secs: number | null;
  avg_agent_word_share: number | null;
  red_flag_rate: number;
  total_red_flags: number;
  period_start: string | null;
  period_end: string | null;
}

export interface AnalyticsOutcomeItem {
  id: string;
  call_log_id: string | null;
  goal_outcome: string | null;
  has_red_flags: boolean;
  red_flag_max_severity: string | null;
  turn_count: number | null;
  call_duration_secs: number | null;
  agent_word_share: number | null;
  created_at: string;
}

export interface RedFlagGroupItem {
  flag_id: string;
  severity: string;
  count: number;
  calls: Array<{
    analytics_id: string;
    call_log_id: string | null;
    evidence: string | null;
    created_at: string;
  }>;
}

export interface AlertItem {
  id: string;
  call_log_id: string | null;
  bot_id: string;
  goal_outcome: string | null;
  red_flag_max_severity: string | null;
  red_flags: Array<{
    id: string;
    severity: string;
    evidence?: string;
    turn_index?: number;
  }> | null;
  created_at: string;
  contact_name: string | null;
  contact_phone: string | null;
}

export interface AlertsResponse {
  total_unacknowledged: number;
  alerts: AlertItem[];
}

export interface TrendPoint {
  date: string;
  total: number;
  outcomes: Record<string, number>;
  red_flag_count: number;
}

export interface CapturedDataFieldSummary {
  field_id: string;
  values: Array<{ value: string; count?: number }>;
  total_captured: number;
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
