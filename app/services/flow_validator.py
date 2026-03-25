"""Flow graph validation before publish.

Checks structural integrity of the flow graph and returns errors
(block publish) and warnings (allow publish but flag issues).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from app.schemas.flow import FlowNodeCreate, FlowEdgeCreate, ValidationResult


# Node types that introduce a delay (safe cycle breakers)
DELAY_NODE_TYPES = {"wait", "delay", "wait_for_event"}

# Node types that branch and require 2+ outgoing edges
CONDITION_NODE_TYPES = {"condition", "ab_split", "if_else"}

# Action node types that should have a "failed" edge
ACTION_NODE_TYPES = {"send_email", "send_sms", "make_call", "webhook", "update_field"}

# Trigger node types (treated as entry nodes)
TRIGGER_NODE_TYPES = {"entry", "trigger_manual", "trigger_post_call", "trigger_campaign_complete"}

# End/exit node types
END_NODE_TYPES = {"end", "end_flow", "goal_met"}


def validate_flow(
    nodes: list[FlowNodeCreate],
    edges: list[FlowEdgeCreate],
) -> ValidationResult:
    """Validate a flow graph for structural correctness.

    Returns a ValidationResult with:
    - errors: issues that block publish
    - warnings: issues that allow publish but should be flagged
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not nodes:
        errors.append({"code": "EMPTY_GRAPH", "message": "Flow has no nodes."})
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # Build index by position (since FlowNodeCreate has no id, use list index)
    node_index = {i: n for i, n in enumerate(nodes)}
    node_types = {i: n.node_type for i, n in enumerate(nodes)}
    node_names = {i: n.name for i, n in enumerate(nodes)}

    # --- Check: exactly one entry (trigger) node ---
    entry_nodes = [i for i, n in enumerate(nodes) if n.node_type in TRIGGER_NODE_TYPES]
    if len(entry_nodes) == 0:
        errors.append({
            "code": "NO_ENTRY",
            "message": "Flow must have exactly one Entry node.",
        })
    elif len(entry_nodes) > 1:
        errors.append({
            "code": "MULTIPLE_ENTRIES",
            "message": f"Flow has {len(entry_nodes)} Entry nodes; exactly one is required.",
        })

    # --- Check: at least one end node ---
    end_nodes = [i for i, n in enumerate(nodes) if n.node_type in END_NODE_TYPES]
    if len(end_nodes) == 0:
        errors.append({
            "code": "NO_END",
            "message": "Flow must have at least one End node.",
        })

    # Build adjacency from source_node_id -> target_node_id.
    # Edges reference UUIDs but in the create context we use indices.
    # For validation at the API layer, edges use source/target UUIDs that
    # correspond to node positions. We'll build adjacency from edges directly.
    #
    # Since FlowNodeCreate has no ID, the validator works with node indices.
    # The caller should map UUIDs to indices before calling, OR we accept
    # edges as (source_idx, target_idx) pairs. For flexibility, we support
    # both UUID-string and integer-index based edges by building a name-based
    # lookup.
    #
    # In practice, the API layer will pass resolved indices. We use
    # source_node_id/target_node_id as opaque keys here.

    adjacency: dict[Any, list[Any]] = defaultdict(list)
    reverse_adj: dict[Any, list[Any]] = defaultdict(list)
    edge_labels: dict[tuple[Any, Any], list[str]] = defaultdict(list)
    outgoing_count: dict[Any, int] = defaultdict(int)

    # Build a set of valid node identifiers (use source_node_id from edges)
    # We use node list indices as canonical IDs for internal validation
    node_ids = set(range(len(nodes)))

    # Map node UUIDs to indices — nodes now have optional id field
    ref_to_idx: dict[Any, int] = {}
    for idx, n in enumerate(nodes):
        if n.id is not None:
            ref_to_idx[n.id] = idx
            ref_to_idx[str(n.id)] = idx

    # Validate edge references
    for e in edges:
        src = ref_to_idx.get(e.source_node_id)
        tgt = ref_to_idx.get(e.target_node_id)
        if src is None:
            errors.append({
                "code": "INVALID_EDGE_SOURCE",
                "message": f"Edge source {e.source_node_id} does not match any node.",
            })
            continue
        if tgt is None:
            errors.append({
                "code": "INVALID_EDGE_TARGET",
                "message": f"Edge target {e.target_node_id} does not match any node.",
            })
            continue
        adjacency[src].append(tgt)
        reverse_adj[tgt].append(src)
        edge_labels[(src, tgt)].append(e.condition_label)
        outgoing_count[src] += 1

    # If we have fatal structural errors, return early
    if any(e["code"] in ("NO_ENTRY", "MULTIPLE_ENTRIES") for e in errors):
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    entry_idx = entry_nodes[0] if entry_nodes else 0

    # --- Check: all nodes reachable from entry ---
    reachable = _bfs(entry_idx, adjacency, node_ids)
    unreachable = node_ids - reachable
    if unreachable:
        names = [node_names.get(i, f"node-{i}") for i in unreachable]
        errors.append({
            "code": "UNREACHABLE_NODES",
            "message": f"Nodes not reachable from Entry: {', '.join(names)}.",
            "node_names": names,
        })

    # --- Check: no disconnected subgraphs ---
    # Already covered by reachability check above; any unreachable node
    # means a disconnected subgraph.

    # --- Check: every path reaches End ---
    # Nodes with no outgoing edges that are NOT end nodes are dead ends
    for idx in node_ids:
        if idx in reachable and not adjacency[idx] and node_types[idx] not in END_NODE_TYPES:
            errors.append({
                "code": "DEAD_END",
                "message": f"Node '{node_names[idx]}' has no outgoing edges and is not an End node.",
                "node_name": node_names[idx],
            })

    # --- Check: no cycles without delay ---
    cycle_errors = _detect_cycles_without_delay(adjacency, node_types, node_names, node_ids)
    errors.extend(cycle_errors)

    # --- Check: condition nodes have 2+ outgoing edges ---
    for idx in node_ids:
        if node_types[idx] in CONDITION_NODE_TYPES:
            out = outgoing_count.get(idx, 0)
            if out < 2:
                errors.append({
                    "code": "CONDITION_MISSING_BRANCHES",
                    "message": (
                        f"Condition node '{node_names[idx]}' has {out} outgoing edge(s); "
                        f"at least 2 are required."
                    ),
                    "node_name": node_names[idx],
                })

    # --- Check: action nodes have a "failed" edge ---
    for idx in node_ids:
        if node_types[idx] in ACTION_NODE_TYPES:
            labels = []
            for tgt in adjacency.get(idx, []):
                labels.extend(edge_labels.get((idx, tgt), []))
            if "failed" not in labels:
                warnings.append({
                    "code": "ACTION_NO_FAILURE_EDGE",
                    "message": (
                        f"Action node '{node_names[idx]}' has no 'failed' edge. "
                        f"Failures will follow the default path."
                    ),
                    "node_name": node_names[idx],
                })

    # --- Check: End nodes should not have outgoing edges ---
    for idx in end_nodes:
        if adjacency.get(idx):
            warnings.append({
                "code": "END_HAS_OUTGOING",
                "message": f"End node '{node_names[idx]}' has outgoing edges which will be ignored.",
                "node_name": node_names[idx],
            })

    # --- Check: Entry node should not have incoming edges ---
    if entry_nodes:
        if reverse_adj.get(entry_idx):
            warnings.append({
                "code": "ENTRY_HAS_INCOMING",
                "message": "Entry node has incoming edges which may cause unexpected behavior.",
            })

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)


def _bfs(start: int, adjacency: dict[Any, list[Any]], all_nodes: set[int]) -> set[int]:
    """BFS from start node, return set of reachable node indices."""
    visited: set[int] = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def _detect_cycles_without_delay(
    adjacency: dict[Any, list[Any]],
    node_types: dict[int, str],
    node_names: dict[int, str],
    all_nodes: set[int],
) -> list[dict[str, Any]]:
    """Detect cycles that don't pass through a delay node.

    Cycles through delay/wait nodes are acceptable (e.g., retry loops).
    Cycles with no delay would cause infinite instant execution.
    """
    errors: list[dict[str, Any]] = []

    # Standard cycle detection via DFS coloring
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {n: WHITE for n in all_nodes}
    parent: dict[int, int | None] = {n: None for n in all_nodes}

    def dfs(node: int, path: list[int]) -> None:
        color[node] = GRAY
        for neighbor in adjacency.get(node, []):
            if neighbor not in all_nodes:
                continue
            if color[neighbor] == GRAY:
                # Found a cycle — extract it
                cycle_start = neighbor
                cycle: list[int] = []
                # Walk back through path to find cycle
                idx = len(path) - 1
                while idx >= 0 and path[idx] != cycle_start:
                    cycle.append(path[idx])
                    idx -= 1
                cycle.append(cycle_start)
                cycle.reverse()

                # Check if any node in the cycle is a delay type
                has_delay = any(
                    node_types.get(n) in DELAY_NODE_TYPES for n in cycle
                )
                if not has_delay:
                    cycle_names = [node_names.get(n, f"node-{n}") for n in cycle]
                    errors.append({
                        "code": "CYCLE_WITHOUT_DELAY",
                        "message": (
                            f"Cycle without delay node detected: "
                            f"{' -> '.join(cycle_names)} -> {node_names.get(cycle_start, '?')}."
                        ),
                        "cycle_nodes": cycle_names,
                    })
            elif color[neighbor] == WHITE:
                parent[neighbor] = node
                dfs(neighbor, path + [neighbor])
        color[node] = BLACK

    for node in all_nodes:
        if color[node] == WHITE:
            dfs(node, [node])

    return errors
