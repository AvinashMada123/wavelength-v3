export interface VoiceOption {
  value: string;
  label: string;
}

export interface VoiceGroup {
  label: string;
  voices: VoiceOption[];
}

export const VOICE_GROUPS: VoiceGroup[] = [
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

export const ALL_VOICES: VoiceOption[] = VOICE_GROUPS.flatMap((g) => g.voices);

export const LANGUAGE_OPTIONS = [
  { value: "en-IN", label: "English (India)" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "hi-IN", label: "Hindi" },
  { value: "ta-IN", label: "Tamil" },
  { value: "te-IN", label: "Telugu" },
  { value: "bn-IN", label: "Bengali" },
  { value: "kn-IN", label: "Kannada" },
  { value: "ml-IN", label: "Malayalam" },
  { value: "gu-IN", label: "Gujarati" },
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
