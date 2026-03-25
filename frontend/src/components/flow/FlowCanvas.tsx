// frontend/src/components/flow/FlowCanvas.tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  type OnConnect,
  BackgroundVariant,
  Panel,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { toast } from "sonner";
import { Loader2 } from "lucide-react";

import type {
  FlowDefinition,
  FlowVersion,
  FlowNodeData,
  FlowEdgeData,
  FlowNodeType,
  ValidationResult,
} from "@/lib/flow-types";
import { getDefaultConfig, NODE_TYPE_REGISTRY } from "@/lib/flow-types";
import { applyDagreLayout } from "@/lib/flow-layout";
import { validateFlowGraph } from "@/lib/flow-validation";
import { useFlowHistory } from "@/hooks/use-flow-history";
import * as flowsApi from "@/lib/flows-api";

import { NodePalette } from "./NodePalette";
import { PropertiesPanel } from "./PropertiesPanel";
import { CanvasToolbar } from "./CanvasToolbar";
import { ValidationPanel } from "./ValidationPanel";
import { FlowDraftProvider } from "./FlowDraftContext";

import { VoiceCallNode } from "./nodes/VoiceCallNode";
import { WhatsAppTemplateNode } from "./nodes/WhatsAppTemplateNode";
import { WhatsAppSessionNode } from "./nodes/WhatsAppSessionNode";
import { AIGenerateNode } from "./nodes/AIGenerateNode";
import { ConditionNode } from "./nodes/ConditionNode";
import { DelayWaitNode } from "./nodes/DelayWaitNode";
import { WaitForEventNode } from "./nodes/WaitForEventNode";
import { GoalMetNode } from "./nodes/GoalMetNode";
import { EndNode } from "./nodes/EndNode";
import { TriggerNode } from "./nodes/TriggerNode";

// ---------------------------------------------------------------------------
// Node type registry for React Flow
// ---------------------------------------------------------------------------
const nodeTypes: NodeTypes = {
  // Triggers
  trigger_post_call: TriggerNode,
  trigger_manual: TriggerNode,
  trigger_campaign_complete: TriggerNode,
  // Actions
  voice_call: VoiceCallNode,
  whatsapp_template: WhatsAppTemplateNode,
  whatsapp_session: WhatsAppSessionNode,
  ai_generate_send: AIGenerateNode,
  goal_met: GoalMetNode,
  end: EndNode,
  // Logic
  condition: ConditionNode,
  delay_wait: DelayWaitNode,
  wait_for_event: WaitForEventNode,
};

// ---------------------------------------------------------------------------
// Helpers: convert between API data and React Flow format
// ---------------------------------------------------------------------------
function apiNodesToRF(apiNodes: FlowNodeData[]): Node[] {
  return apiNodes.map((n) => ({
    id: n.id,
    type: n.node_type,
    position: { x: n.position_x, y: n.position_y },
    data: {
      label: n.name,
      nodeType: n.node_type,
      config: n.config,
    },
  }));
}

function apiEdgesToRF(apiEdges: FlowEdgeData[]): Edge[] {
  return apiEdges.map((e) => ({
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: e.condition_label,
    label: e.condition_label,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { strokeWidth: 2 },
    labelStyle: { fontSize: 11, fontWeight: 500 },
  }));
}

function rfNodesToAPI(rfNodes: Node[], versionId: string): FlowNodeData[] {
  return rfNodes.map((n) => ({
    id: n.id,
    version_id: versionId,
    node_type: (n.data.nodeType || n.type) as FlowNodeType,
    name: (n.data.label as string) || "",
    position_x: n.position.x,
    position_y: n.position.y,
    config: (n.data.config as Record<string, any>) || {},
    created_at: "",
  }));
}

function rfEdgesToAPI(rfEdges: Edge[], versionId: string): FlowEdgeData[] {
  return rfEdges.map((e, i) => ({
    id: e.id,
    version_id: versionId,
    source_node_id: e.source,
    target_node_id: e.target,
    condition_label: (e.sourceHandle as string) || (e.label as string) || "default",
    sort_order: i,
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface FlowCanvasProps {
  flowId: string;
  flow: FlowDefinition;
  version: FlowVersion;
  bots: Array<{ id: string; name: string }>;
  onPublished: () => void;
}

function getInitialNodes(version: FlowVersion): Node[] {
  const apiNodes = version.nodes ?? [];
  if (apiNodes.length > 0) return apiNodesToRF(apiNodes);

  // Empty flow — auto-add a trigger node so the user has a starting point
  return [
    {
      id: crypto.randomUUID(),
      type: "trigger_manual",
      position: { x: 250, y: 50 },
      data: {
        label: "Manual Trigger",
        nodeType: "trigger_manual",
        config: {},
      },
    },
  ];
}

export function FlowCanvas({ flowId, flow, version, bots, onPublished }: FlowCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(getInitialNodes(version));
  const [edges, setEdges, onEdgesChange] = useEdgesState(apiEdgesToRF(version.edges ?? []));
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const history = useFlowHistory();
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const isDraft = version.status === "draft";

  // -----------------------------------------------------------------------
  // Manual save + dirty tracking
  // -----------------------------------------------------------------------
  const [isDirty, setIsDirty] = useState(false);
  const isInitialLoad = useRef(true);

  // Track when nodes/edges change (skip initial load)
  useEffect(() => {
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      return;
    }
    if (isDraft) setIsDirty(true);
  }, [nodes, edges, isDraft]);

  const handleSave = useCallback(async () => {
    if (!isDraft) return;
    setIsSaving(true);
    try {
      await flowsApi.saveGraph(flowId, version.id, {
        nodes: rfNodesToAPI(nodes, version.id),
        edges: rfEdgesToAPI(edges, version.id),
      });
      setIsDirty(false);
      toast.success("Flow saved");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error(`Failed to save flow: ${msg}`);
      console.error("[FlowCanvas] Save failed:", err);
    } finally {
      setIsSaving(false);
    }
  }, [flowId, version.id, isDraft, nodes, edges]);

  // -----------------------------------------------------------------------
  // Connection handler
  // -----------------------------------------------------------------------
  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      history.pushState(nodes, edges, "Connect edge");
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            label: params.sourceHandle || "default",
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { strokeWidth: 2 },
            labelStyle: { fontSize: 11, fontWeight: 500 },
          },
          eds,
        ),
      );
    },
    [nodes, edges, history, setEdges],
  );

  // -----------------------------------------------------------------------
  // Drop handler — add nodes from palette
  // -----------------------------------------------------------------------
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (!isDraft) return;

      const nodeType = event.dataTransfer.getData("application/reactflow-nodetype") as FlowNodeType;
      if (!nodeType) return;

      const info = NODE_TYPE_REGISTRY.find((n) => n.type === nodeType);
      if (!info) return;

      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!reactFlowBounds) return;

      const position = {
        x: event.clientX - reactFlowBounds.left - 110,
        y: event.clientY - reactFlowBounds.top - 40,
      };

      history.pushState(nodes, edges, `Add ${info.label}`);

      const newNode: Node = {
        id: crypto.randomUUID(),
        type: nodeType,
        position,
        data: {
          label: info.label,
          nodeType,
          config: getDefaultConfig(nodeType),
        },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [isDraft, nodes, edges, history, setNodes],
  );

  // -----------------------------------------------------------------------
  // Node selection
  // -----------------------------------------------------------------------
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // -----------------------------------------------------------------------
  // Update node from properties panel
  // -----------------------------------------------------------------------
  const handleUpdateNode = useCallback(
    (nodeId: string, updates: Partial<Node["data"]>) => {
      history.pushState(nodes, edges, "Update node config");
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n,
        ),
      );
      // Update selectedNode reference
      setSelectedNode((prev) =>
        prev && prev.id === nodeId ? { ...prev, data: { ...prev.data, ...updates } } : prev,
      );
    },
    [nodes, edges, history, setNodes],
  );

  // -----------------------------------------------------------------------
  // Delete selected nodes/edges
  // -----------------------------------------------------------------------
  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      history.pushState(nodes, edges, `Delete ${deleted.length} node(s)`);
    },
    [nodes, edges, history],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      history.pushState(nodes, edges, `Delete ${deleted.length} edge(s)`);
    },
    [nodes, edges, history],
  );

  // -----------------------------------------------------------------------
  // Undo / Redo
  // -----------------------------------------------------------------------
  const handleUndo = useCallback(() => {
    const entry = history.undo(nodes, edges);
    if (entry) {
      setNodes(entry.nodes);
      setEdges(entry.edges);
    }
  }, [nodes, edges, history, setNodes, setEdges]);

  const handleRedo = useCallback(() => {
    const entry = history.redo(nodes, edges);
    if (entry) {
      setNodes(entry.nodes);
      setEdges(entry.edges);
    }
  }, [nodes, edges, history, setNodes, setEdges]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if (mod && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleUndo, handleRedo]);

  // -----------------------------------------------------------------------
  // Auto-layout
  // -----------------------------------------------------------------------
  const handleAutoLayout = useCallback(() => {
    history.pushState(nodes, edges, "Auto layout");
    const layouted = applyDagreLayout(nodes, edges);
    setNodes(layouted);
  }, [nodes, edges, history, setNodes]);

  // -----------------------------------------------------------------------
  // Validate
  // -----------------------------------------------------------------------
  const handleValidate = useCallback(async () => {
    setIsValidating(true);
    try {
      // Client-side first for instant feedback
      const clientResult = validateFlowGraph(nodes, edges);
      setValidationResult(clientResult);

      // Then server-side for authoritative result
      const serverResult = await flowsApi.validateFlow(flowId, version.id);
      setValidationResult(serverResult);
    } catch {
      toast.error("Validation failed");
    } finally {
      setIsValidating(false);
    }
  }, [nodes, edges, flowId, version.id]);

  // -----------------------------------------------------------------------
  // Publish
  // -----------------------------------------------------------------------
  const handlePublish = useCallback(async () => {
    setIsPublishing(true);
    try {
      // Save first
      await flowsApi.saveGraph(flowId, version.id, {
        nodes: rfNodesToAPI(nodes, version.id),
        edges: rfEdgesToAPI(edges, version.id),
      });

      // Then validate
      const result = await flowsApi.validateFlow(flowId, version.id);
      if (!result.valid) {
        setValidationResult(result);
        toast.error(`Cannot publish: ${result.errors.length} validation error(s)`);
        return;
      }

      // Publish
      await flowsApi.publishVersion(flowId, version.id);
      toast.success("Flow published successfully!");
      onPublished();
    } catch (err: any) {
      toast.error(err.message || "Failed to publish flow");
    } finally {
      setIsPublishing(false);
    }
  }, [flowId, version.id, nodes, edges, onPublished]);

  // -----------------------------------------------------------------------
  // Simulate (placeholder — opens simulation route)
  // -----------------------------------------------------------------------
  const handleSimulate = useCallback(() => {
    toast.info("Simulation is not yet implemented");
  }, []);

  // -----------------------------------------------------------------------
  // Focus node from validation panel
  // -----------------------------------------------------------------------
  const handleFocusNode = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      if (node) {
        setSelectedNode(node);
      }
    },
    [nodes],
  );

  return (
    <FlowDraftProvider value={isDraft}>
    <div className="flex h-full">
      {/* Left: Node Palette */}
      {isDraft && <NodePalette />}

      {/* Center: Canvas */}
      <div className="relative flex-1" ref={reactFlowWrapper}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={isDraft ? onNodesChange : undefined}
          onEdgesChange={isDraft ? onEdgesChange : undefined}
          onConnect={isDraft ? onConnect : undefined}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onDragOver={onDragOver}
          onDrop={onDrop}
          onNodesDelete={onNodesDelete}
          onEdgesDelete={onEdgesDelete}
          nodeTypes={nodeTypes}
          fitView
          snapToGrid
          snapGrid={[20, 20]}
          deleteKeyCode={isDraft ? ["Backspace", "Delete"] : null}
          className="bg-muted/30"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls position="bottom-left" />
          <MiniMap
            position="bottom-right"
            nodeColor={(n) => {
              const info = NODE_TYPE_REGISTRY.find((r) => r.type === n.type);
              return info ? info.color.replace("border-", "").replace("-500", "") : "#888";
            }}
            maskColor="rgba(0,0,0,0.1)"
          />

          {/* Toolbar */}
          <Panel position="top-center">
            <CanvasToolbar
              canUndo={history.canUndo}
              canRedo={history.canRedo}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onAutoLayout={handleAutoLayout}
              onValidate={handleValidate}
              onPublish={handlePublish}
              onSimulate={handleSimulate}
              onSave={handleSave}
              isPublishing={isPublishing}
              isValidating={isValidating}
              isSaving={isSaving}
              isDirty={isDirty}
              isDraft={isDraft}
            />
          </Panel>

          {/* Unsaved indicator */}
          {isDirty && !isSaving && (
            <Panel position="top-right">
              <div className="rounded-md border border-yellow-500/50 bg-yellow-500/10 px-2 py-1 text-xs text-yellow-500">
                Unsaved changes
              </div>
            </Panel>
          )}
        </ReactFlow>

        {/* Validation results */}
        <ValidationPanel
          result={validationResult}
          onClose={() => setValidationResult(null)}
          onFocusNode={handleFocusNode}
        />
      </div>

      {/* Right: Properties Panel */}
      {selectedNode && (
        <PropertiesPanel
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdateNode={handleUpdateNode}
          bots={bots}
        />
      )}
    </div>
    </FlowDraftProvider>
  );
}
