import { apiFetch } from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FlowSimulateRequest {
  mock_lead: Record<string, any>;
  outcomes?: Record<string, string>;
}

export interface FlowSimulatePathStep {
  node_id: string;
  node_type: string;
  node_name: string;
  action_preview: string | null;
  outcome: string | null;
}

export interface FlowSimulateResponse {
  path: FlowSimulatePathStep[];
  goals_hit: string[];
  end_reason: string;
}

export interface LiveTestRequest {
  phone_number: string;
  delay_ratio?: number;
}

export interface LiveTestResponse {
  instance_id: string;
  is_test: boolean;
  delay_ratio: number;
  phone_number: string;
  status: string;
}

export interface FlowInstanceSummary {
  id: string;
  flow_id: string;
  lead_id: string;
  lead_name?: string;
  lead_phone?: string;
  status: string;
  current_node_id: string | null;
  is_test: boolean;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface FlowTouchpointSummary {
  id: string;
  node_id: string;
  node_name?: string;
  node_type?: string;
  status: string;
  scheduled_at: string;
  executed_at: string | null;
  completed_at: string | null;
  outcome: string | null;
  generated_content: string | null;
  error_message: string | null;
}

export interface FlowTransitionSummary {
  id: string;
  from_node_id: string | null;
  to_node_id: string;
  edge_id: string | null;
  outcome_data: Record<string, any>;
  transitioned_at: string;
}

export interface JourneyData {
  instance: FlowInstanceSummary;
  touchpoints: FlowTouchpointSummary[];
  transitions: FlowTransitionSummary[];
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

/** Dry-run simulation (no side effects) */
export async function simulateFlow(
  flowId: string,
  versionId: string,
  body: FlowSimulateRequest,
): Promise<FlowSimulateResponse> {
  return apiFetch(`/api/flows/${flowId}/versions/${versionId}/simulate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Start a live test instance */
export async function startLiveTest(
  flowId: string,
  body: LiveTestRequest,
): Promise<LiveTestResponse> {
  return apiFetch(`/api/flows/${flowId}/live-test`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Fetch instances for a flow (for leads panel) */
export async function fetchFlowInstances(
  flowId: string,
  params?: { status?: string; is_test?: boolean; page?: number; limit?: number },
): Promise<{ instances: FlowInstanceSummary[]; total: number }> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.is_test !== undefined) search.set("is_test", String(params.is_test));
  if (params?.page) search.set("page", String(params.page));
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiFetch(`/api/flows/${flowId}/instances${qs ? `?${qs}` : ""}`);
}

/** Fetch journey data for a specific instance (for replay) */
export async function fetchJourneyData(
  flowId: string,
  instanceId: string,
): Promise<JourneyData> {
  return apiFetch(`/api/flows/${flowId}/instances/${instanceId}/journey`);
}

/** Cancel a test instance */
export async function cancelFlowInstance(
  flowId: string,
  instanceId: string,
): Promise<void> {
  return apiFetch(`/api/flows/${flowId}/instances/${instanceId}/cancel`, {
    method: "POST",
  });
}
