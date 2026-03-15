import { z } from "zod";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const loginSchema = z.object({
  email: z.string().email("Invalid email"),
  password: z.string().min(1, "Password is required"),
});
export type LoginFormValues = z.infer<typeof loginSchema>;

export const signupSchema = z.object({
  email: z.string().email("Invalid email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  display_name: z.string().min(1, "Name is required"),
  org_name: z.string().min(1, "Organization name is required"),
});
export type SignupFormValues = z.infer<typeof signupSchema>;

// ---------------------------------------------------------------------------
// Bot Config
// ---------------------------------------------------------------------------

const ghlWorkflowSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "Workflow name is required"),
  tag: z.string().min(1, "Tag is required"),
  timing: z.enum(["pre_call", "during_call", "post_call"]),
  enabled: z.boolean(),
  trigger_description: z.string().optional(),
});

const successCriterionSchema = z.object({
  id: z.string(),
  label: z.string().min(1, "Label is required"),
  is_primary: z.boolean().optional(),
});

const redFlagSchema = z.object({
  id: z.string(),
  label: z.string().min(1, "Label is required"),
  severity: z.enum(["critical", "high", "medium", "low"]),
  auto_detect: z.boolean().optional(),
  keywords: z.array(z.string()).optional(),
  detect_in: z.enum(["realtime", "post_call"]).optional(),
});

const dataCaptureFieldSchema = z.object({
  id: z.string(),
  label: z.string().min(1, "Label is required"),
  type: z.enum(["string", "integer", "float", "boolean", "enum"]),
  enum_values: z.array(z.string()).optional(),
  description: z.string().optional(),
});

const goalConfigSchema = z.object({
  version: z.number().optional(),
  goal_type: z.string().min(1, "Goal type is required"),
  goal_description: z.string().min(1, "Goal description is required"),
  success_criteria: z.array(successCriterionSchema),
  red_flags: z.array(redFlagSchema).optional(),
  data_capture_fields: z.array(dataCaptureFieldSchema).optional(),
});

export const botFormSchema = z.object({
  agent_name: z.string().min(1, "Agent name is required"),
  company_name: z.string().min(1, "Company name is required"),
  location: z.string().default(""),
  event_name: z.string().default(""),
  event_date: z.string().default(""),
  event_time: z.string().default(""),
  greeting_template: z.string().default(""),
  stt_provider: z.enum(["deepgram", "sarvam"]).default("deepgram"),
  tts_provider: z.enum(["gemini", "sarvam", "elevenlabs"]).default("sarvam"),
  tts_voice: z.string().min(1, "Voice is required"),
  tts_style_prompt: z.string().default(""),
  llm_provider: z.enum(["google", "groq"]).default("google"),
  llm_model: z.string().min(1, "Model is required"),
  llm_thinking_enabled: z.boolean().default(false),
  language: z.string().default("en-IN"),
  allowed_languages: z.array(z.string()).default([]),
  system_prompt_template: z.string().min(1, "System prompt is required"),
  context_variables: z.record(z.string(), z.string()).default({}),
  silence_timeout_secs: z.number().min(1).max(30).default(5),
  ghl_webhook_url: z.string().default(""),
  ghl_post_call_tag: z.string().default(""),
  ghl_workflows: z.array(ghlWorkflowSchema).default([]),
  max_call_duration: z.number().min(60).max(3600).default(480),
  telephony_provider: z.enum(["plivo", "twilio"]).default("plivo"),
  plivo_caller_id: z.string().default(""),
  twilio_phone_number: z.string().default(""),
  circuit_breaker_enabled: z.boolean().default(true),
  circuit_breaker_threshold: z.number().min(1).max(20).default(3),
  goal_config: goalConfigSchema.nullable().optional(),
});
export type BotFormValues = z.infer<typeof botFormSchema>;

// ---------------------------------------------------------------------------
// Lead
// ---------------------------------------------------------------------------

export const leadSchema = z.object({
  phone_number: z
    .string()
    .min(1, "Phone number is required")
    .regex(/^\+?[\d\s-]{7,15}$/, "Invalid phone number"),
  contact_name: z.string().min(1, "Contact name is required"),
  email: z.string().email("Invalid email").or(z.literal("")).optional(),
  company: z.string().optional(),
  location: z.string().optional(),
  source: z.string().optional(),
});
export type LeadFormValues = z.infer<typeof leadSchema>;

// ---------------------------------------------------------------------------
// Campaign
// ---------------------------------------------------------------------------

export const campaignSchema = z.object({
  name: z.string().min(1, "Campaign name is required"),
  bot_config_id: z.string().min(1, "Bot is required"),
  lead_ids: z.array(z.string()).min(1, "At least one lead is required"),
  concurrency_limit: z.number().min(1).max(50).default(5),
});
export type CampaignFormValues = z.infer<typeof campaignSchema>;

// ---------------------------------------------------------------------------
// Settings — Telephony
// ---------------------------------------------------------------------------

export const telephonyConfigSchema = z.object({
  plivo_auth_id: z.string().optional(),
  plivo_auth_token: z.string().optional(),
  twilio_account_sid: z.string().optional(),
  twilio_auth_token: z.string().optional(),
  ghl_api_key: z.string().optional(),
  ghl_location_id: z.string().optional(),
});
export type TelephonyConfigFormValues = z.infer<typeof telephonyConfigSchema>;

export const phoneNumberSchema = z.object({
  provider: z.enum(["plivo", "twilio"]),
  phone_number: z.string().min(1, "Phone number is required"),
  label: z.string().optional(),
  is_default: z.boolean().default(false),
});
export type PhoneNumberFormValues = z.infer<typeof phoneNumberSchema>;

// ---------------------------------------------------------------------------
// Trigger Call
// ---------------------------------------------------------------------------

export const triggerCallSchema = z.object({
  bot_id: z.string().min(1, "Bot is required"),
  contact_name: z.string().min(1, "Contact name is required"),
  contact_phone: z
    .string()
    .min(1, "Phone number is required")
    .regex(/^\+?[\d\s-]{7,15}$/, "Invalid phone number"),
  ghl_contact_id: z.string().nullable().optional(),
  extra_vars: z.record(z.string(), z.string()).optional(),
});
export type TriggerCallFormValues = z.infer<typeof triggerCallSchema>;

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export const createOrgSchema = z.object({
  name: z.string().min(1, "Organization name is required"),
  plan: z.string().default("free"),
});
export type CreateOrgFormValues = z.infer<typeof createOrgSchema>;

export const createUserSchema = z.object({
  email: z.string().email("Invalid email"),
  display_name: z.string().min(1, "Name is required"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  role: z.string().min(1, "Role is required"),
  org_id: z.string().min(1, "Organization is required"),
});
export type CreateUserFormValues = z.infer<typeof createUserSchema>;

// ---------------------------------------------------------------------------
// Team Invite
// ---------------------------------------------------------------------------

export const inviteSchema = z.object({
  email: z.string().email("Invalid email"),
  role: z.enum(["client_user", "client_admin"]).default("client_user"),
});
export type InviteFormValues = z.infer<typeof inviteSchema>;
