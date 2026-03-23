import { describe, it, expect } from "vitest";
import { getSimulationNodeStyle, getSimulationEdgeStyle } from "../useSimulationStyles";

describe("getSimulationNodeStyle", () => {
  const visited = ["n1", "n2"];
  const currentId = "n2";

  it("highlights current node with ring", () => {
    const style = getSimulationNodeStyle("n2", visited, currentId);
    expect(style.className).toContain("ring-2");
    expect(style.className).toContain("ring-blue-500");
  });

  it("colors visited nodes green", () => {
    const style = getSimulationNodeStyle("n1", visited, currentId);
    expect(style.className).toContain("ring-green-500");
  });

  it("dims unvisited nodes", () => {
    const style = getSimulationNodeStyle("n3", visited, currentId);
    expect(style.opacity).toBe(0.35);
  });
});

describe("getSimulationEdgeStyle", () => {
  const visitedEdges = ["e1"];

  it("colors visited edges green", () => {
    const style = getSimulationEdgeStyle("e1", visitedEdges);
    expect(style.stroke).toBe("#22c55e");
    expect(style.strokeWidth).toBe(3);
  });

  it("dims unvisited edges", () => {
    const style = getSimulationEdgeStyle("e2", visitedEdges);
    expect(style.stroke).toBe("#d1d5db");
    expect(style.opacity).toBe(0.3);
  });
});
