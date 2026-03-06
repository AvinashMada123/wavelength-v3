export interface BotConfig {
  id: string;
  agent_name: string;
  company_name: string;
  location: string | null;
  event_name: string | null;
  event_date: string | null;
  event_time: string | null;
  tts_voice: string;
  tts_style_prompt: string | null;
  system_prompt_template: string;
  silence_timeout_secs: number;
  ghl_webhook_url: string | null;
  plivo_caller_id: string;
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
  tts_voice?: string;
  tts_style_prompt?: string | null;
  system_prompt_template: string;
  silence_timeout_secs?: number;
  ghl_webhook_url?: string | null;
  plivo_auth_id: string;
  plivo_auth_token: string;
  plivo_caller_id: string;
}

export interface UpdateBotConfigRequest {
  agent_name?: string | null;
  company_name?: string | null;
  location?: string | null;
  event_name?: string | null;
  event_date?: string | null;
  event_time?: string | null;
  tts_voice?: string | null;
  tts_style_prompt?: string | null;
  system_prompt_template?: string | null;
  silence_timeout_secs?: number | null;
  ghl_webhook_url?: string | null;
  plivo_auth_id?: string | null;
  plivo_auth_token?: string | null;
  plivo_caller_id?: string | null;
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
  call_sid: string;
  status: string;
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
}
