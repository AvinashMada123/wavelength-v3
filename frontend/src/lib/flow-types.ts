// frontend/src/lib/flow-types.ts

// ---------------------------------------------------------------------------
// Node type definitions
// ---------------------------------------------------------------------------

export type FlowNodeType =
  | "voice_call"
  | "whatsapp_template"
  | "whatsapp_session"
  | "ai_generate_send"
  | "condition"
  | "delay_wait"
  | "wait_for_event"
  | "goal_met"
  | "end";

export type NodeCategory = "action" | "control" | "terminal";

export interface NodeTypeRegistryEntry {
  type: FlowNodeType;
  label: string;
  description: string;
  icon: string;
  color: string;
  category: NodeCategory;
}

export const NODE_TYPE_REGISTRY: NodeTypeRegistryEntry[] = [
  // Actions
  {
    type: "voice_call",
    label: "Voice Call",
    description: "Place an AI voice call to the lead",
    icon: "Phone",
    color: "border-blue-500",
    category: "action",
  },
  {
    type: "whatsapp_template",
    label: "WhatsApp Template",
    description: "Send a pre-approved WhatsApp template message",
    icon: "MessageSquare",
    color: "border-green-500",
    category: "action",
  },
  {
    type: "whatsapp_session",
    label: "WhatsApp Session",
    description: "Send a WhatsApp session message (within 24hr window)",
    icon: "MessageCircle",
    color: "border-emerald-500",
    category: "action",
  },
  {
    type: "ai_generate_send",
    label: "AI Generate & Send",
    description: "Generate a message with AI and send it",
    icon: "Sparkles",
    color: "border-purple-500",
    category: "action",
  },
  // Control
  {
    type: "condition",
    label: "Condition",
    description: "Branch based on lead data or outcomes",
    icon: "GitBranch",
    color: "border-amber-500",
    category: "control",
  },
  {
    type: "delay_wait",
    label: "Delay / Wait",
    description: "Wait for a specified duration before continuing",
    icon: "Clock",
    color: "border-slate-500",
    category: "control",
  },
  {
    type: "wait_for_event",
    label: "Wait for Event",
    description: "Wait for a reply, call completion, or other event",
    icon: "Bell",
    color: "border-cyan-500",
    category: "control",
  },
  // Terminal
  {
    type: "goal_met",
    label: "Goal Met",
    description: "Mark the sequence goal as achieved",
    icon: "Target",
    color: "border-emerald-500",
    category: "terminal",
  },
  {
    type: "end",
    label: "End",
    description: "End the sequence for this lead",
    icon: "CircleStop",
    color: "border-red-500",
    category: "terminal",
  },
];

// ---------------------------------------------------------------------------
// Default configs per node type
// ---------------------------------------------------------------------------

export function getDefaultConfig(nodeType: FlowNodeType): Record<string, any> {
  switch (nodeType) {
    case "voice_call":
      return { bot_id: "", quick_retry: { enabled: false, max_attempts: 3, interval_hours: 1 } };
    case "whatsapp_template":
      return { template_name: "" };
    case "whatsapp_session":
      return { message: "", ai_generation: { enabled: false, prompt: "" }, expects_reply: false };
    case "ai_generate_send":
      return { mode: "full_message", prompt: "", send_via: "whatsapp_session" };
    case "condition":
      return { rules: [], default_label: "other" };
    case "delay_wait":
      return { duration_value: 1, duration_unit: "hours" };
    case "wait_for_event":
      return { event_type: "reply_received", timeout_hours: 24 };
    case "goal_met":
      return { goal_name: "", goal_description: "" };
    case "end":
      return { end_reason: "completed" };
    default:
      return {};
  }
}

// ---------------------------------------------------------------------------
// Flow data types (API shapes)
// ---------------------------------------------------------------------------

export interface FlowNodeData {
  id: string;
  version_id: string;
  node_type: FlowNodeType;
  name: string;
  position_x: number;
  position_y: number;
  config: Record<string, any>;
  created_at: string;
}

export interface FlowEdgeData {
  id: string;
  version_id: string;
  source_node_id: string;
  target_node_id: string;
  condition_label: string;
  sort_order: number;
}

export interface FlowVersion {
  id: string;
  flow_id: string;
  version_number: number;
  status: "draft" | "published" | "archived";
  nodes: FlowNodeData[];
  edges: FlowEdgeData[];
  created_at: string;
  published_at: string | null;
}

export interface FlowDefinition {
  id: string;
  sequence_id: string;
  name: string;
  description: string;
  published_version: FlowVersion | null;
  draft_version: FlowVersion | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Validation types
// ---------------------------------------------------------------------------

export interface ValidationIssue {
  message: string;
  node_id: string | null;
  severity: "error" | "warning";
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}
