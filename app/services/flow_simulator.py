"""Flow dry-run simulator.

Walks the flow graph using a mock lead and predetermined outcomes
at each branch point, producing a preview of the execution path.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.schemas.flow import (
    FlowNodeCreate,
    FlowEdgeCreate,
    SimulateRequest,
    SimulateResponse,
)


# Maximum steps to prevent runaway simulation
MAX_SIMULATION_STEPS = 200

# Node types that represent goals
GOAL_NODE_TYPES = {"goal", "conversion"}

# Terminal node type
END_NODE_TYPE = "end"
ENTRY_NODE_TYPE = "entry"


def simulate_flow(
    nodes: list[FlowNodeCreate],
    edges: list[FlowEdgeCreate],
    mock_lead: dict[str, Any],
    outcomes: dict[str, str],
) -> SimulateResponse:
    """Simulate a flow execution without side effects.

    Args:
        nodes: The flow's node definitions.
        edges: The flow's edge definitions.
        mock_lead: Fake lead data used for action previews.
        outcomes: Maps node_id (as string) -> outcome label to take at
                  branch/condition nodes. For nodes not in this dict,
                  the "default" edge is followed.

    Returns:
        SimulateResponse with the traversal path, goals hit, and end reason.
    """
    if not nodes:
        return SimulateResponse(path=[], goals_hit=[], end_reason="empty_graph")

    # Build node index by list position
    node_by_idx: dict[int, FlowNodeCreate] = {i: n for i, n in enumerate(nodes)}

    # Map edge source/target UUIDs to node indices
    edge_refs: set[Any] = set()
    for e in edges:
        edge_refs.add(e.source_node_id)
        edge_refs.add(e.target_node_id)

    sorted_refs = sorted(edge_refs, key=str)
    ref_to_idx: dict[Any, int] = {}
    for idx, ref in enumerate(sorted_refs):
        if idx < len(nodes):
            ref_to_idx[ref] = idx

    idx_to_ref: dict[int, Any] = {v: k for k, v in ref_to_idx.items()}

    # Build adjacency: source_idx -> list of (target_idx, label, sort_order)
    adjacency: dict[int, list[tuple[int, str, int]]] = defaultdict(list)
    for e in edges:
        src = ref_to_idx.get(e.source_node_id)
        tgt = ref_to_idx.get(e.target_node_id)
        if src is not None and tgt is not None:
            adjacency[src].append((tgt, e.condition_label, e.sort_order))

    # Sort edges by sort_order for deterministic traversal
    for src in adjacency:
        adjacency[src].sort(key=lambda x: x[2])

    # Find entry node
    entry_idx: int | None = None
    for i, n in enumerate(nodes):
        if n.node_type == ENTRY_NODE_TYPE:
            entry_idx = i
            break

    if entry_idx is None:
        return SimulateResponse(path=[], goals_hit=[], end_reason="no_entry_node")

    # Walk the graph
    path: list[dict[str, Any]] = []
    goals_hit: list[str] = []
    visited_count: dict[int, int] = defaultdict(int)
    current_idx = entry_idx
    end_reason: str | None = None

    for step in range(MAX_SIMULATION_STEPS):
        if current_idx is None:
            end_reason = "no_next_node"
            break

        node = node_by_idx.get(current_idx)
        if node is None:
            end_reason = "invalid_node"
            break

        visited_count[current_idx] += 1

        # Build path entry
        node_ref_str = str(idx_to_ref.get(current_idx, current_idx))
        step_entry: dict[str, Any] = {
            "step": step + 1,
            "node_id": node_ref_str,
            "node_type": node.node_type,
            "node_name": node.name,
            "action_preview": _build_action_preview(node, mock_lead),
        }
        path.append(step_entry)

        # Check for goal
        if node.node_type in GOAL_NODE_TYPES:
            goal_name = node.config.get("goal_name", node.name)
            goals_hit.append(goal_name)

        # Terminal node
        if node.node_type == END_NODE_TYPE:
            end_reason = "reached_end"
            break

        # Prevent infinite loops (allow revisiting up to 3 times for loops)
        if visited_count[current_idx] > 3:
            end_reason = "loop_detected"
            break

        # Determine which edge to follow
        outgoing = adjacency.get(current_idx, [])
        if not outgoing:
            end_reason = "dead_end"
            break

        # Check if the outcomes dict has a choice for this node
        desired_outcome = outcomes.get(node_ref_str)

        next_idx: int | None = None
        if desired_outcome:
            # Find edge matching the desired outcome
            for tgt, label, _ in outgoing:
                if label == desired_outcome:
                    next_idx = tgt
                    break

        if next_idx is None:
            # Fall back to "default" edge
            for tgt, label, _ in outgoing:
                if label == "default":
                    next_idx = tgt
                    break

        if next_idx is None:
            # Take the first available edge
            next_idx = outgoing[0][0]

        step_entry["edge_taken"] = desired_outcome or "default"
        current_idx = next_idx
    else:
        end_reason = "max_steps_exceeded"

    return SimulateResponse(
        path=path,
        goals_hit=goals_hit,
        end_reason=end_reason,
    )


def _build_action_preview(
    node: FlowNodeCreate,
    mock_lead: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a preview of what the action node would do with the mock lead.

    Substitutes lead variables into templates where applicable.
    """
    config = node.config
    if not config:
        return None

    preview: dict[str, Any] = {"node_type": node.node_type}

    # Template variable substitution for common fields
    template_fields = ("message", "subject", "body", "sms_body", "email_body")
    for field in template_fields:
        if field in config:
            preview[field] = _substitute_variables(config[field], mock_lead)

    # Show condition expression for condition nodes
    if "condition" in config:
        preview["condition"] = config["condition"]

    # Show wait duration for delay nodes
    if "duration" in config:
        preview["duration"] = config["duration"]
    if "wait_hours" in config:
        preview["wait_hours"] = config["wait_hours"]

    # Show webhook URL
    if "webhook_url" in config:
        preview["webhook_url"] = config["webhook_url"]

    # Show field update details
    if "field_name" in config:
        preview["field_name"] = config["field_name"]
        preview["field_value"] = _substitute_variables(
            str(config.get("field_value", "")), mock_lead
        )

    return preview if len(preview) > 1 else None


def _substitute_variables(template: str, lead: dict[str, Any]) -> str:
    """Replace {{variable}} placeholders with mock lead data."""
    result = template
    for key, value in lead.items():
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value))
    return result
