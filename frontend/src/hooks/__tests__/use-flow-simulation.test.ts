import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useFlowSimulation } from "../use-flow-simulation";
import type { FlowGraph, MockLead } from "@/lib/flow-simulation";

const MOCK_LEAD: MockLead = {
  name: "Test Lead",
  phone: "+919876543210",
  interest_level: 8,
};

const SIMPLE_GRAPH: FlowGraph = {
  nodes: [
    { id: "n1", type: "voice_call", name: "Call", config: {}, position: { x: 0, y: 0 } },
    { id: "n2", type: "end", name: "End", config: {}, position: { x: 0, y: 200 } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2", condition_label: "default" },
  ],
  entryNodeId: "n1",
};

describe("useFlowSimulation", () => {
  it("starts inactive", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    expect(result.current.isActive).toBe(false);
    expect(result.current.simulationState).toBeNull();
  });

  it("starts simulation with mock lead", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    expect(result.current.isActive).toBe(true);
    expect(result.current.simulationState?.currentNodeId).toBe("n1");
  });

  it("advances to next node", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.next("default"));
    expect(result.current.simulationState?.currentNodeId).toBe("n2");
    expect(result.current.simulationState?.status).toBe("completed");
  });

  it("provides action preview", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    expect(result.current.actionPreview?.nodeType).toBe("voice_call");
  });

  it("resets simulation", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.next("default"));
    act(() => result.current.reset());
    expect(result.current.simulationState?.currentNodeId).toBe("n1");
  });

  it("stops simulation", () => {
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.stop());
    expect(result.current.isActive).toBe(false);
    expect(result.current.simulationState).toBeNull();
  });

  it("auto-plays through flow with delays", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useFlowSimulation(SIMPLE_GRAPH));
    act(() => result.current.start(MOCK_LEAD));
    act(() => result.current.autoPlay(500)); // 500ms between steps

    await act(async () => { vi.advanceTimersByTime(600); });
    expect(result.current.simulationState?.currentNodeId).toBe("n2");
    vi.useRealTimers();
  });
});
