import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// Mock the API before importing the hook
vi.mock("@/lib/flows-api", () => ({
  fetchFlowInstances: vi.fn(),
  fetchJourneyData: vi.fn(),
}));

import { fetchFlowInstances, fetchJourneyData } from "@/lib/flows-api";
import { useFlowJourney } from "../use-flow-journey";

const MOCK_INSTANCES = {
  instances: [
    {
      id: "inst-1",
      flow_id: "f1",
      lead_id: "l1",
      lead_name: "Rahul",
      lead_phone: "+919876543210",
      status: "completed",
      current_node_id: null,
      is_test: false,
      started_at: "2026-03-20T10:00:00Z",
      completed_at: "2026-03-21T10:00:00Z",
      error_message: null,
    },
    {
      id: "inst-2",
      flow_id: "f1",
      lead_id: "l2",
      lead_name: "Priya",
      lead_phone: "+919123456780",
      status: "error",
      current_node_id: "n3",
      is_test: false,
      started_at: "2026-03-20T12:00:00Z",
      completed_at: null,
      error_message: "WhatsApp send failed",
    },
  ],
  total: 2,
};

const MOCK_JOURNEY = {
  instance: MOCK_INSTANCES.instances[0],
  touchpoints: [
    { id: "tp1", node_id: "n1", status: "completed", outcome: "picked_up", scheduled_at: "2026-03-20T10:00:00Z", executed_at: "2026-03-20T10:01:00Z", completed_at: "2026-03-20T10:05:00Z", generated_content: null, error_message: null },
    { id: "tp2", node_id: "n2", status: "completed", outcome: "interested", scheduled_at: "2026-03-20T10:05:00Z", executed_at: "2026-03-20T10:05:00Z", completed_at: "2026-03-20T10:05:00Z", generated_content: null, error_message: null },
    { id: "tp3", node_id: "n3", status: "completed", outcome: null, scheduled_at: "2026-03-20T11:00:00Z", executed_at: "2026-03-20T11:00:00Z", completed_at: "2026-03-20T11:01:00Z", generated_content: "Hi Rahul, thanks for your interest!", error_message: null },
  ],
  transitions: [
    { id: "tr1", from_node_id: null, to_node_id: "n1", edge_id: null, outcome_data: {}, transitioned_at: "2026-03-20T10:00:00Z" },
    { id: "tr2", from_node_id: "n1", to_node_id: "n2", edge_id: "e1", outcome_data: { call_outcome: "picked_up" }, transitioned_at: "2026-03-20T10:05:00Z" },
    { id: "tr3", from_node_id: "n2", to_node_id: "n3", edge_id: "e2", outcome_data: { condition: "interested" }, transitioned_at: "2026-03-20T10:05:00Z" },
  ],
};

describe("useFlowJourney", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchFlowInstances as ReturnType<typeof vi.fn>).mockResolvedValue(MOCK_INSTANCES);
    (fetchJourneyData as ReturnType<typeof vi.fn>).mockResolvedValue(MOCK_JOURNEY);
  });

  it("loads instances on mount", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
      expect(result.current!.instances).toHaveLength(2);
    });

    expect(fetchFlowInstances).toHaveBeenCalledWith("f1", expect.any(Object));
  });

  it("selects an instance and loads journey", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
      expect(result.current!.instances).toHaveLength(2);
    });

    await act(async () => {
      result.current!.selectInstance("inst-1");
    });

    await waitFor(() => {
      expect(result.current!.journeyData).not.toBeNull();
    });

    expect(result.current!.visitedNodeIds).toContain("n1");
    expect(result.current!.visitedNodeIds).toContain("n2");
    expect(result.current!.visitedNodeIds).toContain("n3");
    expect(result.current!.visitedEdgeIds).toContain("e1");
    expect(result.current!.visitedEdgeIds).toContain("e2");
  });

  it("identifies error nodes", async () => {
    (fetchJourneyData as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...MOCK_JOURNEY,
      instance: MOCK_INSTANCES.instances[1],
      touchpoints: [
        ...MOCK_JOURNEY.touchpoints.slice(0, 2),
        { ...MOCK_JOURNEY.touchpoints[2], status: "failed", error_message: "Send failed" },
      ],
    });

    const { result } = renderHook(() => useFlowJourney("f1"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
      expect(result.current!.instances).toHaveLength(2);
    });

    await act(async () => {
      result.current!.selectInstance("inst-2");
    });

    await waitFor(() => {
      expect(result.current!.journeyData).not.toBeNull();
    });

    expect(result.current!.errorNodeIds).toContain("n3");
  });

  it("filters instances by status", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
      expect(result.current!.instances).toHaveLength(2);
    });

    await act(async () => {
      result.current!.setStatusFilter("error");
    });

    await waitFor(() => {
      expect(fetchFlowInstances).toHaveBeenCalledWith("f1", expect.objectContaining({ status: "error" }));
    });
  });

  it("clears selection", async () => {
    const { result } = renderHook(() => useFlowJourney("f1"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
      expect(result.current!.instances).toHaveLength(2);
    });

    await act(async () => {
      result.current!.selectInstance("inst-1");
    });

    await waitFor(() => {
      expect(result.current!.journeyData).not.toBeNull();
    });

    act(() => {
      result.current!.clearSelection();
    });

    expect(result.current!.selectedInstanceId).toBeNull();
    expect(result.current!.journeyData).toBeNull();
    expect(result.current!.visitedNodeIds).toEqual([]);
  });
});
