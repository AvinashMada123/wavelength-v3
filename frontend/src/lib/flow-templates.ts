// frontend/src/lib/flow-templates.ts

export interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
}

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "blank",
    name: "Blank Flow",
    description: "Start from scratch with an empty canvas",
    icon: "FileText",
  },
  {
    id: "post_call_followup",
    name: "Post-Call Follow-Up",
    description: "Automated follow-up sequence after a voice call",
    icon: "PhoneForwarded",
  },
  {
    id: "missed_call_recovery",
    name: "Missed Call Recovery",
    description: "Re-engage leads who missed or declined a call",
    icon: "PhoneMissed",
  },
  {
    id: "nurture_sequence",
    name: "Nurture Sequence",
    description: "Multi-touch nurture flow with delays and conditions",
    icon: "Sprout",
  },
];
