// (or wherever FlowCanvas is defined in Plan 3)

// Additional imports for simulation
import { useFlowSimulation } from "@/hooks/use-flow-simulation";
import { useFlowJourney } from "@/hooks/use-flow-journey";
import { SimulationToolbar } from "@/components/flow/SimulationToolbar";
import { SimulationSummary } from "@/components/flow/SimulationSummary";
import { LiveTestDialog } from "@/components/flow/LiveTestDialog";
import { LeadsPanel } from "@/components/flow/LeadsPanel";
import { JourneyOverlay } from "@/components/flow/JourneyOverlay";
import {
  getSimulationNodeStyle,
  getSimulationEdgeStyle,
  getJourneyNodeStyle,
  getJourneyEdgeStyle,
} from "@/components/flow/useSimulationStyles";

// Inside the canvas component:
export default function FlowCanvasPage() {
  // ... existing Plan 3 state (nodes, edges, version, etc.)

  // --- Simulation ---
  const graph: FlowGraph = {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      name: n.data.name,
      config: n.data.config,
      position: n.position,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      condition_label: e.data?.conditionLabel ?? "default",
    })),
    entryNodeId: nodes.find((n) => /* no incoming edges */)?.id ?? nodes[0]?.id,
  };

  const simulation = useFlowSimulation(graph);
  const journey = useFlowJourney(flowId);
  const [liveTestOpen, setLiveTestOpen] = useState(false);

  // --- Apply visual styles ---
  // In the node rendering, apply simulation/journey styles:
  const getNodeClassName = (nodeId: string) => {
    if (simulation.isActive && simulation.simulationState) {
      return getSimulationNodeStyle(
        nodeId,
        simulation.simulationState.visitedNodeIds,
        simulation.simulationState.currentNodeId,
      );
    }
    if (journey.selectedInstanceId) {
      return getJourneyNodeStyle(
        nodeId,
        journey.visitedNodeIds,
        journey.errorNodeIds,
        journey.currentNodeId,
      );
    }
    return { className: "", opacity: 1 };
  };

  const getEdgeStyle = (edgeId: string) => {
    if (simulation.isActive && simulation.simulationState) {
      return getSimulationEdgeStyle(edgeId, simulation.simulationState.visitedEdgeIds);
    }
    if (journey.selectedInstanceId) {
      return getJourneyEdgeStyle(edgeId, journey.visitedEdgeIds);
    }
    return { stroke: "#64748b", strokeWidth: 2, opacity: 1, animated: false };
  };

  return (
    <div className="relative h-full">
      {/* Canvas Toolbar — add simulation + test buttons */}
      <div className="absolute left-1/2 top-4 z-50 -translate-x-1/2">
        {simulation.isActive ? (
          <SimulationToolbar simulation={simulation} graph={graph} />
        ) : (
          <div className="flex items-center gap-2">
            {/* ... existing toolbar buttons from Plan 3 */}
            <SimulationToolbar simulation={simulation} graph={graph} />
            <Button
              size="sm"
              variant="outline"
              onClick={() => setLiveTestOpen(true)}
            >
              Live Test
            </Button>
            <LeadsPanel journey={journey} />
          </div>
        )}
      </div>

      {/* React Flow canvas with styled nodes/edges */}
      <ReactFlow
        nodes={nodes.map((n) => ({
          ...n,
          data: { ...n.data, simStyle: getNodeClassName(n.id) },
        }))}
        edges={edges.map((e) => ({
          ...e,
          style: getEdgeStyle(e.id),
          animated: getEdgeStyle(e.id).animated,
        }))}
        // ... other React Flow props
      />

      {/* Simulation summary overlay */}
      {simulation.isActive && simulation.journeySummary?.endReason !== "active" && (
        <div className="absolute bottom-4 right-4 z-50">
          <SimulationSummary summary={simulation.journeySummary!} />
        </div>
      )}

      {/* Journey replay overlay */}
      <JourneyOverlay journey={journey} />

      {/* Live test dialog */}
      <LiveTestDialog
        open={liveTestOpen}
        onOpenChange={setLiveTestOpen}
        flowId={flowId}
        onTestStarted={(instanceId) => {
          journey.refresh();
          toast.success("Live test started — check the Leads panel to track progress");
        }}
      />
    </div>
  );
}
