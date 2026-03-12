export interface VoiceOption {
  value: string;
  label: string;
}

export interface VoiceGroup {
  label: string;
  voices: VoiceOption[];
}

export const GEMINI_VOICE_GROUPS: VoiceGroup[] = [
  {
    label: "Female",
    voices: [
      { value: "Kore", label: "Kore" },
      { value: "Aoede", label: "Aoede" },
      { value: "Leda", label: "Leda" },
      { value: "Despina", label: "Despina" },
      { value: "Callirrhoe", label: "Callirrhoe" },
      { value: "Erinome", label: "Erinome" },
      { value: "Laomedeia", label: "Laomedeia" },
      { value: "Pulcherrima", label: "Pulcherrima" },
      { value: "Vindemiatrix", label: "Vindemiatrix" },
    ],
  },
  {
    label: "Male",
    voices: [
      { value: "Puck", label: "Puck" },
      { value: "Charon", label: "Charon" },
      { value: "Fenrir", label: "Fenrir" },
      { value: "Orus", label: "Orus" },
      { value: "Zephyr", label: "Zephyr" },
      { value: "Achernar", label: "Achernar" },
      { value: "Achird", label: "Achird" },
      { value: "Enceladus", label: "Enceladus" },
      { value: "Iapetus", label: "Iapetus" },
      { value: "Umbriel", label: "Umbriel" },
    ],
  },
  {
    label: "Neutral",
    voices: [
      { value: "Algenib", label: "Algenib" },
      { value: "Algieba", label: "Algieba" },
      { value: "Alnilam", label: "Alnilam" },
      { value: "Autonoe", label: "Autonoe" },
      { value: "Gacrux", label: "Gacrux" },
      { value: "Sulafat", label: "Sulafat" },
    ],
  },
];

export const SARVAM_VOICE_GROUPS: VoiceGroup[] = [
  {
    label: "Female",
    voices: [
      { value: "priya", label: "Priya" },
      { value: "ritu", label: "Ritu" },
      { value: "neha", label: "Neha" },
      { value: "pooja", label: "Pooja" },
      { value: "simran", label: "Simran" },
      { value: "kavya", label: "Kavya" },
      { value: "ishita", label: "Ishita" },
      { value: "shreya", label: "Shreya" },
      { value: "roopa", label: "Roopa" },
      { value: "tanya", label: "Tanya" },
      { value: "shruti", label: "Shruti" },
      { value: "rupali", label: "Rupali" },
      { value: "amelia", label: "Amelia" },
      { value: "sophia", label: "Sophia" },
    ],
  },
  {
    label: "Male",
    voices: [
      { value: "shubh", label: "Shubh" },
      { value: "aditya", label: "Aditya" },
      { value: "rahul", label: "Rahul" },
      { value: "rohan", label: "Rohan" },
      { value: "amit", label: "Amit" },
      { value: "dev", label: "Dev" },
      { value: "varun", label: "Varun" },
      { value: "kabir", label: "Kabir" },
      { value: "advait", label: "Advait" },
      { value: "ashutosh", label: "Ashutosh" },
      { value: "ratan", label: "Ratan" },
      { value: "manan", label: "Manan" },
      { value: "sumit", label: "Sumit" },
      { value: "aayan", label: "Aayan" },
      { value: "tarun", label: "Tarun" },
      { value: "sunny", label: "Sunny" },
      { value: "vijay", label: "Vijay" },
      { value: "mohit", label: "Mohit" },
    ],
  },
];

// Backward compat: default VOICE_GROUPS = Gemini
export const VOICE_GROUPS = GEMINI_VOICE_GROUPS;

export const ALL_VOICES: VoiceOption[] = GEMINI_VOICE_GROUPS.flatMap((g) => g.voices);

export const STT_PROVIDER_OPTIONS = [
  { value: "deepgram", label: "Deepgram" },
  { value: "sarvam", label: "Sarvam AI" },
] as const;

// Client-facing labels (no vendor names)
export const STT_PROVIDER_OPTIONS_CLIENT = [
  { value: "sarvam", label: "Model 1" },
  { value: "deepgram", label: "Model 2" },
] as const;

export const TTS_PROVIDER_OPTIONS = [
  { value: "gemini", label: "Gemini" },
  { value: "sarvam", label: "Sarvam AI" },
] as const;

export const LLM_PROVIDER_OPTIONS = [
  { value: "google", label: "Google Gemini" },
  { value: "groq", label: "Groq" },
] as const;

export const LLM_MODEL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  google: [
    { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
  ],
  groq: [
    { value: "llama-3.3-70b-versatile", label: "Llama 3.3 70B Versatile" },
    { value: "llama-3.1-8b-instant", label: "Llama 3.1 8B Instant" },
    { value: "openai/gpt-oss-20b", label: "GPT-OSS 20B (no tools)" },
  ],
};

export const LANGUAGE_OPTIONS = [
  { value: "unknown", label: "Multi (Auto-detect)" },
  { value: "en-IN", label: "English (India)" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "hi-IN", label: "Hindi" },
  { value: "mr-IN", label: "Marathi" },
  { value: "ta-IN", label: "Tamil" },
  { value: "te-IN", label: "Telugu" },
  { value: "bn-IN", label: "Bengali" },
  { value: "kn-IN", label: "Kannada" },
  { value: "ml-IN", label: "Malayalam" },
  { value: "gu-IN", label: "Gujarati" },
  { value: "pa-IN", label: "Punjabi" },
  { value: "or-IN", label: "Odia" },
  { value: "as-IN", label: "Assamese" },
  { value: "ur-IN", label: "Urdu" },
];

// Pre-defined template variables (always available, filled at call time)
export const BUILTIN_VARIABLES = [
  "contact_name",
  "agent_name",
  "company_name",
  "location",
  "event_name",
  "event_date",
  "event_time",
];
