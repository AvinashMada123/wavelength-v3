# Flow Builder Plan 3: API Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete REST API layer for the flow builder: CRUD for flows/versions/nodes/edges, atomic graph save, instance management, validation, simulation, live test, and all Pydantic schemas.

**Architecture:** Single `app/api/flows.py` router following the same patterns as `app/api/sequences.py` — FastAPI `APIRouter`, `get_current_user`/`get_current_org` auth dependencies, SQLAlchemy async sessions, Pydantic response models with `ConfigDict(from_attributes=True)`. Validation logic lives in a separate `app/services/flow_validator.py` for reuse by the publish and validate endpoints.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy (async), Pydantic v2, pytest

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §6, §7, §8, §12

**Depends on:** Plan 2 (data models must exist: `FlowDefinition`, `FlowVersion`, `FlowNode`, `FlowEdge`, `FlowInstance`, `FlowTouchpoint`, `FlowTransition`, `FlowEvent`)

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `app/api/flows.py` | All flow API endpoints (CRUD, versions, nodes/edges, instances, simulation) |
| Create | `app/schemas/flow.py` | Pydantic request/response schemas for flows |
| Create | `app/services/flow_validator.py` | Graph validation logic (errors + warnings) |
| Create | `app/services/flow_simulator.py` | Dry-run simulation engine |
| Modify | `app/main.py` | Register `flows.router` |
| Create | `tests/test_flows_api.py` | Tests for flow CRUD + version management |
| Create | `tests/test_flows_graph_api.py` | Tests for atomic graph save + node/edge CRUD |
| Create | `tests/test_flows_instances_api.py` | Tests for instance management endpoints |
| Create | `tests/test_flow_validator.py` | Tests for validation logic |
| Create | `tests/test_flow_simulator.py` | Tests for simulation engine |

---

## Task 1: Pydantic Schemas

**Files:**
- Create: `app/schemas/flow.py`

- [ ] **Step 1: Create the schemas module**

```python
# app/schemas/flow.py
"""Pydantic schemas for Flow Builder API request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums as string literals (matching SQLAlchemy model enums)
# ---------------------------------------------------------------------------

NODE_TYPES = [
    "voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send",
    "condition", "delay_wait", "wait_for_event", "goal_met", "end",
]

VERSION_STATUSES = ["draft", "published", "archived"]
INSTANCE_STATUSES = ["active", "paused", "completed", "cancelled", "error"]
TOUCHPOINT_STATUSES = ["pending", "executing", "waiting", "completed", "failed", "skipped"]


# ---------------------------------------------------------------------------
# Flow Definition schemas
# ---------------------------------------------------------------------------

class FlowCreate(BaseModel):
    name: str
    description: str | None = None
    trigger_type: str = "manual"
    trigger_conditions: dict[str, Any] = Field(default_factory=dict)
    max_active_per_lead: int = 1
    variables: list[dict[str, Any]] = Field(default_factory=list)


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_conditions: dict[str, Any] | None = None
    max_active_per_lead: int | None = None
    variables: list[dict[str, Any]] | None = None
    is_active: bool | None = None


class FlowListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    trigger_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Computed fields added by the endpoint
    published_version: int | None = None
    draft_version: int | None = None
    active_instance_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class PaginatedFlows(BaseModel):
    items: list[FlowListItem]
    total: int
    page: int
    page_size: int


class FlowResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_conditions: dict[str, Any]
    max_active_per_lead: int
    variables: list[dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Include current versions inline
    current_draft: VersionSummary | None = None
    current_published: VersionSummary | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Flow Version schemas
# ---------------------------------------------------------------------------

class VersionSummary(BaseModel):
    id: uuid.UUID
    version_number: int
    status: str
    is_locked: bool
    published_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VersionListItem(BaseModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    version_number: int
    status: str
    is_locked: bool
    published_at: datetime | None
    published_by: uuid.UUID | None
    created_at: datetime
    node_count: int = 0
    edge_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class NodeResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    org_id: uuid.UUID
    node_type: str
    name: str
    position_x: float
    position_y: float
    config: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EdgeResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    org_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    condition_label: str | None
    sort_order: int

    model_config = ConfigDict(from_attributes=True)


class VersionDetailResponse(BaseModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    version_number: int
    status: str
    is_locked: bool
    published_at: datetime | None
    published_by: uuid.UUID | None
    created_at: datetime
    nodes: list[NodeResponse] = Field(default_factory=list)
    edges: list[EdgeResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Atomic graph save schemas
# ---------------------------------------------------------------------------

class NodeInput(BaseModel):
    """Node payload for atomic graph save. `id` is optional (omit for new nodes)."""
    id: uuid.UUID | None = None
    node_type: str
    name: str
    position_x: float = 0.0
    position_y: float = 0.0
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeInput(BaseModel):
    """Edge payload for atomic graph save. `id` is optional (omit for new edges)."""
    id: uuid.UUID | None = None
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    condition_label: str | None = None
    sort_order: int = 0


class GraphSaveRequest(BaseModel):
    """Full graph payload for PUT /api/flows/{id}/versions/{vid}.
    Replaces all nodes and edges in a single transaction."""
    nodes: list[NodeInput]
    edges: list[EdgeInput]


class GraphSaveResponse(BaseModel):
    """Response after atomic graph save — returns the full version with new IDs."""
    version: VersionDetailResponse
    node_id_map: dict[str, str] = Field(
        default_factory=dict,
        description="Maps client-provided temp IDs to server-assigned UUIDs (for new nodes)",
    )


# ---------------------------------------------------------------------------
# Individual node/edge CRUD schemas
# ---------------------------------------------------------------------------

class NodeCreate(BaseModel):
    node_type: str
    name: str
    position_x: float = 0.0
    position_y: float = 0.0
    config: dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    name: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    config: dict[str, Any] | None = None


class NodePositionUpdate(BaseModel):
    node_id: uuid.UUID
    position_x: float
    position_y: float


class BulkLayoutUpdate(BaseModel):
    positions: list[NodePositionUpdate]


class EdgeCreate(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    condition_label: str | None = None
    sort_order: int = 0


# ---------------------------------------------------------------------------
# Validation schemas
# ---------------------------------------------------------------------------

class ValidationError(BaseModel):
    code: str
    message: str
    node_id: uuid.UUID | None = None
    edge_id: uuid.UUID | None = None


class ValidationWarning(BaseModel):
    code: str
    message: str
    node_id: uuid.UUID | None = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationWarning] = Field(default_factory=list)


class PublishResponse(BaseModel):
    version: VersionSummary
    validation: ValidationResult


# ---------------------------------------------------------------------------
# Simulation schemas
# ---------------------------------------------------------------------------

class SimulationRequest(BaseModel):
    mock_lead: dict[str, Any] = Field(
        default_factory=dict,
        description="Mock lead data: name, phone, interest_level, etc.",
    )
    outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="Pre-set outcomes for action nodes: {node_id: 'picked_up'}",
    )


class SimulationStep(BaseModel):
    node_id: uuid.UUID
    node_type: str
    node_name: str
    action_preview: str | None = None
    outcome: str | None = None
    condition_matched: str | None = None


class SimulationResult(BaseModel):
    path: list[SimulationStep]
    goals_hit: list[str] = Field(default_factory=list)
    end_reason: str


# ---------------------------------------------------------------------------
# Live test schemas
# ---------------------------------------------------------------------------

class LiveTestRequest(BaseModel):
    phone_number: str
    delay_compression_ratio: float = Field(
        default=60.0,
        description="Compression ratio for delays: 60 means 1 hour becomes 1 minute",
    )
    context_data: dict[str, Any] = Field(default_factory=dict)


class LiveTestResponse(BaseModel):
    instance_id: uuid.UUID
    message: str = "Live test started"


# ---------------------------------------------------------------------------
# Instance management schemas
# ---------------------------------------------------------------------------

class EnrollRequest(BaseModel):
    lead_ids: list[uuid.UUID]
    context_data: dict[str, Any] = Field(default_factory=dict)


class EnrollResponse(BaseModel):
    enrolled: list[uuid.UUID]
    skipped: list[SkippedLead] = Field(default_factory=list)


class SkippedLead(BaseModel):
    lead_id: uuid.UUID
    reason: str


# Fix forward reference
EnrollResponse.model_rebuild()


class FlowInstanceListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    flow_id: uuid.UUID
    version_id: uuid.UUID
    lead_id: uuid.UUID
    trigger_call_id: uuid.UUID | None
    status: str
    current_node_id: uuid.UUID | None
    is_test: bool
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedFlowInstances(BaseModel):
    items: list[FlowInstanceListItem]
    total: int
    page: int
    page_size: int


class FlowTransitionResponse(BaseModel):
    id: uuid.UUID
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    edge_id: uuid.UUID | None
    outcome_data: dict[str, Any]
    transitioned_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlowTouchpointResponse(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    node_id: uuid.UUID
    org_id: uuid.UUID
    lead_id: uuid.UUID
    node_snapshot: dict[str, Any]
    status: str
    scheduled_at: datetime
    executed_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    generated_content: str | None
    error_message: str | None
    retry_count: int
    max_retries: int
    messaging_provider_id: str | None
    queued_call_id: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class FlowInstanceDetailResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    flow_id: uuid.UUID
    version_id: uuid.UUID
    lead_id: uuid.UUID
    trigger_call_id: uuid.UUID | None
    status: str
    current_node_id: uuid.UUID | None
    context_data: dict[str, Any]
    error_message: str | None
    is_test: bool
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    touchpoints: list[FlowTouchpointResponse] = Field(default_factory=list)
    transitions: list[FlowTransitionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Clone schema
# ---------------------------------------------------------------------------

class CloneRequest(BaseModel):
    name: str | None = None  # defaults to "{original_name} (Copy)"
```

- [ ] **Step 2: Verify imports work**

```bash
cd /path/to/project && python -c "from app.schemas.flow import *; print('All schemas loaded OK')"
```

- [ ] **Step 3: Commit**

```bash
git add app/schemas/flow.py
git commit -m "feat: add Pydantic schemas for flow builder API

Request/response models for flow CRUD, version management, atomic
graph save, node/edge operations, validation, simulation, live test,
and instance management. Follows existing sequence API patterns."
```

---

## Task 2: Flow Validation Service

**Files:**
- Create: `app/services/flow_validator.py`
- Create: `tests/test_flow_validator.py`

- [ ] **Step 1: Write failing tests for flow validation**

```python
# tests/test_flow_validator.py
"""Tests for flow graph validation logic."""

import uuid
import pytest
from app.services.flow_validator import validate_flow_graph
from app.schemas.flow import ValidationResult


def _node(node_type: str, node_id: uuid.UUID | None = None, config: dict | None = None):
    """Helper to create a minimal node dict for testing."""
    return {
        "id": node_id or uuid.uuid4(),
        "node_type": node_type,
        "name": f"Test {node_type}",
        "config": config or {},
    }


def _edge(source_id: uuid.UUID, target_id: uuid.UUID, label: str | None = None):
    """Helper to create a minimal edge dict for testing."""
    return {
        "id": uuid.uuid4(),
        "source_node_id": source_id,
        "target_node_id": target_id,
        "condition_label": label,
        "sort_order": 0,
    }


class TestValidationErrors:
    """Tests for errors that block publishing."""

    def test_empty_graph_fails(self):
        result = validate_flow_graph(nodes=[], edges=[])
        assert not result.valid
        assert any(e.code == "NO_NODES" for e in result.errors)

    def test_no_start_node_fails(self):
        """A graph with no node that has zero incoming edges fails."""
        n1 = _node("voice_call")
        n2 = _node("end")
        # Circular: n1 -> n2 -> n1, no entry point
        edges = [
            _edge(n1["id"], n2["id"]),
            _edge(n2["id"], n1["id"]),
        ]
        result = validate_flow_graph(nodes=[n1, n2], edges=edges)
        assert not result.valid
        assert any(e.code == "NO_ENTRY_NODE" for e in result.errors)

    def test_multiple_start_nodes_fails(self):
        """Graph with multiple disconnected entry points fails."""
        n1 = _node("voice_call")
        n2 = _node("voice_call")
        n3 = _node("end")
        n4 = _node("end")
        edges = [_edge(n1["id"], n3["id"]), _edge(n2["id"], n4["id"])]
        result = validate_flow_graph(nodes=[n1, n2, n3, n4], edges=edges)
        assert not result.valid
        assert any(e.code == "MULTIPLE_ENTRY_NODES" for e in result.errors)

    def test_unreachable_node_fails(self):
        """Nodes not reachable from entry fail validation."""
        n1 = _node("voice_call")
        n2 = _node("end")
        n3 = _node("voice_call")  # Disconnected
        edges = [_edge(n1["id"], n2["id"])]
        result = validate_flow_graph(nodes=[n1, n2, n3], edges=edges)
        assert not result.valid
        assert any(e.code == "UNREACHABLE_NODE" for e in result.errors)

    def test_dead_end_non_terminal_fails(self):
        """Non-terminal nodes without outgoing edges fail."""
        n1 = _node("voice_call")
        n2 = _node("voice_call")  # No outgoing edge, not an End node
        edges = [_edge(n1["id"], n2["id"])]
        result = validate_flow_graph(nodes=[n1, n2], edges=edges)
        assert not result.valid
        assert any(e.code == "DEAD_END" for e in result.errors)

    def test_cycle_without_delay_fails(self):
        """Cycles without a delay/wait node cause instant infinite loops."""
        n1 = _node("voice_call")
        n2 = _node("condition")
        edges = [_edge(n1["id"], n2["id"]), _edge(n2["id"], n1["id"])]
        result = validate_flow_graph(nodes=[n1, n2], edges=edges)
        assert not result.valid
        assert any(e.code == "CYCLE_NO_DELAY" for e in result.errors)

    def test_condition_node_needs_two_edges(self):
        """Condition nodes must have at least 2 outgoing edges."""
        n1 = _node("voice_call")
        n2 = _node("condition")
        n3 = _node("end")
        edges = [_edge(n1["id"], n2["id"]), _edge(n2["id"], n3["id"])]
        result = validate_flow_graph(nodes=[n1, n2, n3], edges=edges)
        assert not result.valid
        assert any(e.code == "CONDITION_INSUFFICIENT_EDGES" for e in result.errors)

    def test_convergence_on_action_node_fails(self):
        """Multiple incoming edges on action nodes are not allowed."""
        n1 = _node("condition")
        n2 = _node("voice_call")
        n3 = _node("voice_call")
        n4 = _node("voice_call")  # Two incoming
        n5 = _node("end")
        edges = [
            _edge(n1["id"], n2["id"], "a"),
            _edge(n1["id"], n3["id"], "b"),
            _edge(n2["id"], n4["id"]),
            _edge(n3["id"], n4["id"]),  # Second incoming to action node
            _edge(n4["id"], n5["id"]),
        ]
        result = validate_flow_graph(nodes=[n1, n2, n3, n4, n5], edges=edges)
        assert not result.valid
        assert any(e.code == "CONVERGENCE_ON_ACTION" for e in result.errors)


class TestValidationSuccess:
    """Tests for valid graphs."""

    def test_minimal_valid_graph(self):
        """voice_call -> end is valid."""
        n1 = _node("voice_call")
        n2 = _node("end")
        edges = [_edge(n1["id"], n2["id"])]
        result = validate_flow_graph(nodes=[n1, n2], edges=edges)
        assert result.valid
        assert len(result.errors) == 0

    def test_branching_with_condition(self):
        """Start -> condition -> (branch A -> end, branch B -> end) is valid."""
        n1 = _node("voice_call")
        n2 = _node("condition")
        n3 = _node("voice_call")
        n4 = _node("voice_call")
        n5 = _node("end")
        edges = [
            _edge(n1["id"], n2["id"]),
            _edge(n2["id"], n3["id"], "picked_up"),
            _edge(n2["id"], n4["id"], "no_answer"),
            _edge(n3["id"], n5["id"]),
            _edge(n4["id"], n5["id"]),
        ]
        # Convergence on End node is allowed
        result = validate_flow_graph(nodes=[n1, n2, n3, n4, n5], edges=edges)
        assert result.valid

    def test_cycle_with_delay_is_valid(self):
        """Cycles containing a delay node are OK (retry loops)."""
        n1 = _node("voice_call")
        n2 = _node("condition")
        n3 = _node("delay_wait")
        n4 = _node("end")
        edges = [
            _edge(n1["id"], n2["id"]),
            _edge(n2["id"], n3["id"], "no_answer"),
            _edge(n2["id"], n4["id"], "picked_up"),
            _edge(n3["id"], n1["id"]),  # Retry loop, but has delay
        ]
        result = validate_flow_graph(nodes=[n1, n2, n3, n4], edges=edges)
        assert result.valid

    def test_convergence_on_control_node_allowed(self):
        """Multiple incoming edges on delay/condition/end nodes are fine."""
        n1 = _node("condition")
        n2 = _node("voice_call")
        n3 = _node("voice_call")
        n4 = _node("delay_wait")  # Control node — convergence OK
        n5 = _node("end")
        edges = [
            _edge(n1["id"], n2["id"], "a"),
            _edge(n1["id"], n3["id"], "b"),
            _edge(n2["id"], n4["id"]),
            _edge(n3["id"], n4["id"]),
            _edge(n4["id"], n5["id"]),
        ]
        result = validate_flow_graph(nodes=[n1, n2, n3, n4, n5], edges=edges)
        assert result.valid


class TestValidationWarnings:
    """Tests for warnings (don't block publish)."""

    def test_no_goal_met_node_warns(self):
        n1 = _node("voice_call")
        n2 = _node("end")
        edges = [_edge(n1["id"], n2["id"])]
        result = validate_flow_graph(nodes=[n1, n2], edges=edges)
        assert result.valid
        assert any(w.code == "NO_GOAL_NODE" for w in result.warnings)

    def test_short_delay_warns(self):
        n1 = _node("voice_call")
        n2 = _node("delay_wait", config={"delay_seconds": 120})  # 2 minutes
        n3 = _node("condition")
        n4 = _node("end")
        edges = [
            _edge(n1["id"], n2["id"]),
            _edge(n2["id"], n3["id"]),
            _edge(n3["id"], n1["id"], "retry"),
            _edge(n3["id"], n4["id"], "done"),
        ]
        result = validate_flow_graph(nodes=[n1, n2, n3, n4], edges=edges)
        assert any(w.code == "SHORT_DELAY" for w in result.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_flow_validator.py -v
```

Expected: FAIL — `app.services.flow_validator` does not exist

- [ ] **Step 3: Implement the flow validator**

```python
# app/services/flow_validator.py
"""Flow graph validation logic.

Validates flow graphs for structural correctness before publishing.
Used by both the validate and publish endpoints.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from app.schemas.flow import ValidationError, ValidationResult, ValidationWarning

# Node types that are allowed to have multiple incoming edges (convergence)
CONTROL_NODES = {"condition", "delay_wait", "wait_for_event", "goal_met", "end"}

# Node types that terminate a path (no outgoing edge required)
TERMINAL_NODES = {"end", "goal_met"}

# Action node types that require a `failed` edge
ACTION_NODES = {
    "voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send",
}

# Minimum delay in seconds before we warn about short retry loops
MIN_DELAY_WARNING_SECONDS = 300  # 5 minutes


def validate_flow_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> ValidationResult:
    """Validate a flow graph and return errors + warnings.

    Args:
        nodes: List of node dicts with at minimum {id, node_type, name, config}.
        edges: List of edge dicts with {id, source_node_id, target_node_id, condition_label}.

    Returns:
        ValidationResult with valid=True only if zero errors.
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    if not nodes:
        errors.append(ValidationError(code="NO_NODES", message="Flow has no nodes"))
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # Build lookup structures
    node_map: dict[uuid.UUID, dict] = {n["id"]: n for n in nodes}
    node_ids = set(node_map.keys())

    outgoing: dict[uuid.UUID, list[dict]] = defaultdict(list)
    incoming: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for edge in edges:
        src = edge["source_node_id"]
        tgt = edge["target_node_id"]
        outgoing[src].append(edge)
        incoming[tgt].append(edge)

    # --- Check 1: Identify entry nodes (no incoming edges) ---
    entry_nodes = [nid for nid in node_ids if nid not in incoming or len(incoming[nid]) == 0]

    if len(entry_nodes) == 0:
        errors.append(ValidationError(
            code="NO_ENTRY_NODE",
            message="No entry node found — every node has incoming edges (circular graph)",
        ))
    elif len(entry_nodes) > 1:
        errors.append(ValidationError(
            code="MULTIPLE_ENTRY_NODES",
            message=f"Found {len(entry_nodes)} entry nodes — flow must have exactly one entry point",
        ))

    # --- Check 2: Reachability from entry ---
    if len(entry_nodes) == 1:
        reachable = _bfs(entry_nodes[0], outgoing)
        unreachable = node_ids - reachable
        for nid in unreachable:
            errors.append(ValidationError(
                code="UNREACHABLE_NODE",
                message=f"Node '{node_map[nid]['name']}' is not reachable from the entry point",
                node_id=nid,
            ))

    # --- Check 3: Dead ends (non-terminal nodes with no outgoing edges) ---
    for nid, node in node_map.items():
        if node["node_type"] not in TERMINAL_NODES and len(outgoing.get(nid, [])) == 0:
            errors.append(ValidationError(
                code="DEAD_END",
                message=f"Node '{node['name']}' ({node['node_type']}) has no outgoing edges",
                node_id=nid,
            ))

    # --- Check 4: Cycles without delay/wait ---
    cycles = _find_cycles(node_ids, outgoing)
    for cycle in cycles:
        cycle_types = {node_map[nid]["node_type"] for nid in cycle}
        has_delay = bool(cycle_types & {"delay_wait", "wait_for_event"})
        if not has_delay:
            errors.append(ValidationError(
                code="CYCLE_NO_DELAY",
                message="Cycle detected without a delay/wait node — would cause instant infinite loop",
            ))

    # --- Check 5: Condition nodes need >= 2 outgoing edges ---
    for nid, node in node_map.items():
        if node["node_type"] == "condition":
            out_count = len(outgoing.get(nid, []))
            if out_count < 2:
                errors.append(ValidationError(
                    code="CONDITION_INSUFFICIENT_EDGES",
                    message=f"Condition node '{node['name']}' needs at least 2 outgoing edges, has {out_count}",
                    node_id=nid,
                ))

    # --- Check 6: Convergence only on control/terminal nodes ---
    for nid, node in node_map.items():
        if node["node_type"] not in CONTROL_NODES and len(incoming.get(nid, [])) > 1:
            errors.append(ValidationError(
                code="CONVERGENCE_ON_ACTION",
                message=f"Action node '{node['name']}' has multiple incoming edges — convergence only allowed on control/terminal nodes",
                node_id=nid,
            ))

    # --- Check 7: Action nodes must have required config ---
    for nid, node in node_map.items():
        if node["node_type"] in ACTION_NODES:
            config = node.get("config", {})
            if not config:
                errors.append(ValidationError(
                    code="MISSING_CONFIG",
                    message=f"Action node '{node['name']}' has empty configuration",
                    node_id=nid,
                ))

    # --- Warnings ---

    # No Goal Met node
    if not any(n["node_type"] == "goal_met" for n in nodes):
        warnings.append(ValidationWarning(
            code="NO_GOAL_NODE",
            message="Flow has no Goal Met node — consider adding one to track conversions",
        ))

    # Short delays in retry loops
    for nid, node in node_map.items():
        if node["node_type"] == "delay_wait":
            delay = node.get("config", {}).get("delay_seconds", 0)
            if 0 < delay < MIN_DELAY_WARNING_SECONDS:
                warnings.append(ValidationWarning(
                    code="SHORT_DELAY",
                    message=f"Delay node '{node['name']}' has a {delay}s delay — very short delays in retry loops can be aggressive",
                    node_id=nid,
                ))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _bfs(start: uuid.UUID, outgoing: dict[uuid.UUID, list[dict]]) -> set[uuid.UUID]:
    """Breadth-first search returning all reachable node IDs."""
    visited: set[uuid.UUID] = set()
    queue = [start]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for edge in outgoing.get(current, []):
            target = edge["target_node_id"]
            if target not in visited:
                queue.append(target)
    return visited


def _find_cycles(
    node_ids: set[uuid.UUID],
    outgoing: dict[uuid.UUID, list[dict]],
) -> list[list[uuid.UUID]]:
    """Find all simple cycles using DFS. Returns list of cycles (each a list of node IDs)."""
    cycles: list[list[uuid.UUID]] = []
    visited: set[uuid.UUID] = set()

    def dfs(node: uuid.UUID, path: list[uuid.UUID], path_set: set[uuid.UUID]):
        visited.add(node)
        path.append(node)
        path_set.add(node)

        for edge in outgoing.get(node, []):
            target = edge["target_node_id"]
            if target in path_set:
                # Found a cycle — extract it
                cycle_start = path.index(target)
                cycles.append(path[cycle_start:])
            elif target not in visited:
                dfs(target, path, path_set)

        path.pop()
        path_set.discard(node)

    for nid in node_ids:
        if nid not in visited:
            dfs(nid, [], set())

    return cycles
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_flow_validator.py -v
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/services/flow_validator.py tests/test_flow_validator.py
git commit -m "feat: add flow graph validation service

Validates structural correctness: single entry node, full reachability,
no dead ends, no instant cycles, condition branching rules, convergence
restrictions. Returns errors (block publish) and warnings (advisory)."
```

---

## Task 3: Flow Simulation Service

**Files:**
- Create: `app/services/flow_simulator.py`
- Create: `tests/test_flow_simulator.py`

- [ ] **Step 1: Write failing tests for simulation**

```python
# tests/test_flow_simulator.py
"""Tests for flow simulation (dry-run) engine."""

import uuid
import pytest
from app.services.flow_simulator import simulate_flow
from app.schemas.flow import SimulationResult


def _node(node_type: str, node_id: uuid.UUID | None = None, name: str = "", config: dict | None = None):
    nid = node_id or uuid.uuid4()
    return {
        "id": nid,
        "node_type": node_type,
        "name": name or f"Test {node_type}",
        "config": config or {},
    }


def _edge(source_id: uuid.UUID, target_id: uuid.UUID, label: str | None = None):
    return {
        "id": uuid.uuid4(),
        "source_node_id": source_id,
        "target_node_id": target_id,
        "condition_label": label,
        "sort_order": 0,
    }


class TestSimulation:

    def test_linear_flow(self):
        """voice_call -> end should produce a 2-step path."""
        n1 = _node("voice_call", name="Call Lead")
        n2 = _node("end", name="Done")
        edges = [_edge(n1["id"], n2["id"])]
        outcomes = {str(n1["id"]): "picked_up"}

        result = simulate_flow(
            nodes=[n1, n2],
            edges=edges,
            mock_lead={"name": "Test Lead", "phone": "+1234567890"},
            outcomes=outcomes,
        )

        assert len(result.path) == 2
        assert result.path[0].node_type == "voice_call"
        assert result.path[0].outcome == "picked_up"
        assert result.path[1].node_type == "end"
        assert result.end_reason == "reached_end"

    def test_branching_with_condition(self):
        """Condition node routes based on mock data."""
        n1 = _node("voice_call", name="Initial Call")
        n2 = _node("condition", name="Check Interest", config={
            "conditions": [
                {"label": "interested", "rules": [{"field": "interest_level", "operator": "gte", "value": 7}]},
            ],
            "default_label": "not_interested",
        })
        n3 = _node("goal_met", name="Goal: Interested", config={"goal_name": "interested"})
        n4 = _node("end", name="End Not Interested")
        n5 = _node("end", name="End Interested")

        edges = [
            _edge(n1["id"], n2["id"]),
            _edge(n2["id"], n3["id"], "interested"),
            _edge(n2["id"], n4["id"], "not_interested"),
            _edge(n3["id"], n5["id"]),
        ]
        outcomes = {str(n1["id"]): "picked_up"}

        # High interest → should take "interested" branch
        result = simulate_flow(
            nodes=[n1, n2, n3, n4, n5],
            edges=edges,
            mock_lead={"interest_level": 9},
            outcomes=outcomes,
        )

        assert any(s.node_type == "goal_met" for s in result.path)
        assert "interested" in result.goals_hit

    def test_max_steps_prevents_infinite_loop(self):
        """Simulation stops after max_steps to prevent runaway."""
        n1 = _node("delay_wait", config={"delay_seconds": 3600})
        n2 = _node("condition", config={
            "conditions": [{"label": "loop", "rules": [{"field": "x", "operator": "eq", "value": 1}]}],
            "default_label": "loop",
        })
        edges = [_edge(n1["id"], n2["id"]), _edge(n2["id"], n1["id"], "loop")]

        result = simulate_flow(
            nodes=[n1, n2],
            edges=edges,
            mock_lead={"x": 999},
            outcomes={},
            max_steps=20,
        )

        assert result.end_reason == "max_steps_reached"
        assert len(result.path) <= 20

    def test_action_node_without_outcome_uses_default(self):
        """Action nodes without pre-set outcomes use 'completed' default."""
        n1 = _node("whatsapp_template", name="Send Template")
        n2 = _node("end", name="Done")
        edges = [_edge(n1["id"], n2["id"])]

        result = simulate_flow(
            nodes=[n1, n2],
            edges=edges,
            mock_lead={},
            outcomes={},  # No outcomes provided
        )

        assert result.path[0].outcome == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_flow_simulator.py -v
```

Expected: FAIL — `app.services.flow_simulator` does not exist

- [ ] **Step 3: Implement the simulator**

```python
# app/services/flow_simulator.py
"""Flow simulation (dry-run) engine.

Walks the graph with mock lead data and pre-set outcomes.
No side effects — purely deterministic traversal.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from app.schemas.flow import SimulationResult, SimulationStep

# Node types where we evaluate conditions to pick the outgoing edge
CONDITION_NODES = {"condition"}

# Node types that represent goals
GOAL_NODES = {"goal_met"}

# Node types that terminate the flow
TERMINAL_NODES = {"end", "goal_met"}

# Action nodes that produce an outcome
ACTION_NODES = {
    "voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send",
}

DEFAULT_MAX_STEPS = 100

# Condition operators
OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: _num(a) > _num(b),
    "gte": lambda a, b: _num(a) >= _num(b),
    "lt": lambda a, b: _num(a) < _num(b),
    "lte": lambda a, b: _num(a) <= _num(b),
    "contains": lambda a, b: str(b) in str(a),
    "not_contains": lambda a, b: str(b) not in str(a),
}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def simulate_flow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    mock_lead: dict[str, Any],
    outcomes: dict[str, str],
    max_steps: int = DEFAULT_MAX_STEPS,
) -> SimulationResult:
    """Simulate a flow traversal with mock data.

    Args:
        nodes: Node dicts with {id, node_type, name, config}.
        edges: Edge dicts with {source_node_id, target_node_id, condition_label, sort_order}.
        mock_lead: Mock lead profile data for condition evaluation.
        outcomes: Pre-set outcomes for action nodes: {node_id_str: "picked_up"}.
        max_steps: Safety limit to prevent infinite simulation.

    Returns:
        SimulationResult with path, goals_hit, and end_reason.
    """
    node_map: dict[uuid.UUID, dict] = {n["id"]: n for n in nodes}

    outgoing: dict[uuid.UUID, list[dict]] = defaultdict(list)
    incoming_count: dict[uuid.UUID, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge["source_node_id"]].append(edge)
        incoming_count[edge["target_node_id"]] += 1

    # Sort outgoing edges by sort_order for deterministic condition evaluation
    for nid in outgoing:
        outgoing[nid].sort(key=lambda e: e.get("sort_order", 0))

    # Find entry node (no incoming edges)
    entry_nodes = [nid for nid in node_map if incoming_count.get(nid, 0) == 0]
    if not entry_nodes:
        return SimulationResult(path=[], goals_hit=[], end_reason="no_entry_node")

    current_id = entry_nodes[0]
    path: list[SimulationStep] = []
    goals_hit: list[str] = []
    context = dict(mock_lead)  # Mutable copy, accumulates during simulation

    for _ in range(max_steps):
        node = node_map.get(current_id)
        if node is None:
            return SimulationResult(path=path, goals_hit=goals_hit, end_reason="invalid_node_reference")

        step = SimulationStep(
            node_id=node["id"],
            node_type=node["node_type"],
            node_name=node["name"],
        )

        # Process node based on type
        if node["node_type"] in ACTION_NODES:
            outcome = outcomes.get(str(node["id"]), "completed")
            step.outcome = outcome
            step.action_preview = _action_preview(node, context)

        elif node["node_type"] in CONDITION_NODES:
            matched_label = _evaluate_conditions(node, context)
            step.condition_matched = matched_label

        elif node["node_type"] in GOAL_NODES:
            goal_name = node.get("config", {}).get("goal_name", "unnamed_goal")
            goals_hit.append(goal_name)

        elif node["node_type"] == "delay_wait":
            delay = node.get("config", {}).get("delay_seconds", 0)
            step.action_preview = f"Wait {delay}s"

        elif node["node_type"] == "wait_for_event":
            event_type = node.get("config", {}).get("event_type", "unknown")
            step.action_preview = f"Wait for {event_type}"

        path.append(step)

        # Terminal nodes end the simulation
        if node["node_type"] == "end":
            return SimulationResult(path=path, goals_hit=goals_hit, end_reason="reached_end")

        if node["node_type"] == "goal_met":
            # Goal met continues to next node if edges exist, otherwise ends
            out_edges = outgoing.get(current_id, [])
            if not out_edges:
                return SimulationResult(path=path, goals_hit=goals_hit, end_reason="reached_goal")
            current_id = out_edges[0]["target_node_id"]
            continue

        # Find next node
        out_edges = outgoing.get(current_id, [])
        if not out_edges:
            return SimulationResult(path=path, goals_hit=goals_hit, end_reason="dead_end")

        if node["node_type"] in CONDITION_NODES:
            # Route by condition label
            matched = step.condition_matched
            next_edge = next((e for e in out_edges if e.get("condition_label") == matched), None)
            if next_edge is None:
                # Fall through to first edge
                next_edge = out_edges[0]
            current_id = next_edge["target_node_id"]

        elif node["node_type"] in ACTION_NODES and step.outcome:
            # Route by outcome label if edges have condition_labels
            labeled_edges = [e for e in out_edges if e.get("condition_label")]
            if labeled_edges:
                next_edge = next(
                    (e for e in labeled_edges if e.get("condition_label") == step.outcome),
                    out_edges[0],
                )
            else:
                next_edge = out_edges[0]
            current_id = next_edge["target_node_id"]

        else:
            # Default: follow first edge
            current_id = out_edges[0]["target_node_id"]

    return SimulationResult(path=path, goals_hit=goals_hit, end_reason="max_steps_reached")


def _evaluate_conditions(node: dict, context: dict) -> str:
    """Evaluate condition node against context data. Returns matched label."""
    config = node.get("config", {})
    conditions = config.get("conditions", [])
    default_label = config.get("default_label", "default")

    for condition in conditions:
        label = condition.get("label", "unknown")
        rules = condition.get("rules", [])
        all_match = True

        for rule in rules:
            field = rule.get("field", "")
            operator = rule.get("operator", "eq")
            expected = rule.get("value")
            actual = context.get(field)

            op_fn = OPERATORS.get(operator)
            if op_fn is None or actual is None:
                all_match = False
                break

            if not op_fn(actual, expected):
                all_match = False
                break

        if all_match:
            return label

    return default_label


def _action_preview(node: dict, context: dict) -> str:
    """Generate a human-readable preview of what an action node would do."""
    config = node.get("config", {})
    node_type = node["node_type"]

    if node_type == "voice_call":
        bot_name = config.get("bot_name", "Default Bot")
        return f"Call using bot: {bot_name}"

    elif node_type == "whatsapp_template":
        template_name = config.get("template_name", "unknown")
        return f"Send WhatsApp template: {template_name}"

    elif node_type == "whatsapp_session":
        if config.get("ai_generation", {}).get("enabled"):
            return "Send AI-generated WhatsApp message"
        return f"Send WhatsApp message: {config.get('message', '')[:50]}"

    elif node_type == "ai_generate_send":
        model = config.get("model", "default")
        return f"AI generate + send via {model}"

    return f"Execute {node_type}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_flow_simulator.py -v
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/services/flow_simulator.py tests/test_flow_simulator.py
git commit -m "feat: add flow simulation (dry-run) engine

Walks the graph with mock lead data and pre-set outcomes. Evaluates
condition nodes, tracks goals, generates action previews. Pure
function with no side effects — max_steps safety limit included."
```

---

## Task 4: Flow CRUD Endpoints

**Files:**
- Create: `app/api/flows.py`
- Create: `tests/test_flows_api.py`

- [ ] **Step 1: Write failing tests for flow CRUD**

```python
# tests/test_flows_api.py
"""Tests for flow CRUD and version management API endpoints."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.org_id = uuid.uuid4()
    user.role = "client_admin"
    user.status = "active"
    return user


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def auth_overrides(mock_user, mock_db):
    """Override auth and db dependencies for testing."""
    from app.auth.dependencies import get_current_user, get_current_org
    from app.database import get_db

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_org] = lambda: mock_user.org_id
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Flow CRUD tests
# ---------------------------------------------------------------------------

class TestListFlows:

    @pytest.mark.asyncio
    async def test_list_flows_empty(self, auth_overrides, mock_db):
        """GET /api/flows returns empty paginated list."""
        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        # Mock items query
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, items_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/flows")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_list_flows_with_search(self, auth_overrides, mock_db):
        """GET /api/flows?search=onboard filters by name."""
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, items_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/flows?search=onboard")

        assert resp.status_code == 200


class TestCreateFlow:

    @pytest.mark.asyncio
    async def test_create_flow_success(self, auth_overrides, mock_db, mock_user):
        """POST /api/flows creates flow + draft version."""
        # Mock duplicate name check → no duplicate
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=dup_result)

        # Mock refresh to populate fields
        flow_id = uuid.uuid4()
        version_id = uuid.uuid4()
        now = datetime.utcnow()

        async def fake_refresh(obj):
            if hasattr(obj, "trigger_type"):  # FlowDefinition
                obj.id = flow_id
                obj.org_id = mock_user.org_id
                obj.created_at = now
                obj.updated_at = now
                obj.is_active = True
            else:  # FlowVersion
                obj.id = version_id
                obj.flow_id = flow_id
                obj.version_number = 1
                obj.status = "draft"
                obj.is_locked = False
                obj.published_at = None
                obj.created_at = now

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/flows", json={
                "name": "Onboarding Flow",
                "description": "Welcome new leads",
                "trigger_type": "manual",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Onboarding Flow"

    @pytest.mark.asyncio
    async def test_create_flow_duplicate_name(self, auth_overrides, mock_db):
        """POST /api/flows with duplicate name returns 409."""
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute = AsyncMock(return_value=dup_result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/flows", json={"name": "Existing Flow"})

        assert resp.status_code == 409


class TestGetFlow:

    @pytest.mark.asyncio
    async def test_get_flow_not_found(self, auth_overrides, mock_db):
        """GET /api/flows/{id} returns 404 for missing flow."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{uuid.uuid4()}")

        assert resp.status_code == 404


class TestDeleteFlow:

    @pytest.mark.asyncio
    async def test_delete_flow_with_active_instances(self, auth_overrides, mock_db):
        """DELETE /api/flows/{id} blocked when active instances exist."""
        flow_mock = MagicMock()
        flow_mock.id = uuid.uuid4()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = flow_mock

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3  # 3 active instances

        mock_db.execute = AsyncMock(side_effect=[flow_result, count_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/flows/{flow_mock.id}")

        assert resp.status_code == 409
```

- [ ] **Step 2: Create the flows API router with CRUD endpoints**

```python
# app/api/flows.py
"""REST API for flow builder: CRUD, versions, nodes/edges, instances, simulation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.flow import (
    FlowDefinition,
    FlowEdge,
    FlowEvent,
    FlowInstance,
    FlowNode,
    FlowTouchpoint,
    FlowTransition,
    FlowVersion,
)
from app.models.user import User
from app.schemas.flow import (
    BulkLayoutUpdate,
    CloneRequest,
    EdgeCreate,
    EdgeResponse,
    EnrollRequest,
    EnrollResponse,
    FlowCreate,
    FlowInstanceDetailResponse,
    FlowInstanceListItem,
    FlowListItem,
    FlowResponse,
    FlowTouchpointResponse,
    FlowTransitionResponse,
    FlowUpdate,
    GraphSaveRequest,
    GraphSaveResponse,
    LiveTestRequest,
    LiveTestResponse,
    NodeCreate,
    NodeResponse,
    NodeUpdate,
    PaginatedFlowInstances,
    PaginatedFlows,
    PublishResponse,
    SimulationRequest,
    SimulationResult,
    SkippedLead,
    ValidationResult,
    VersionDetailResponse,
    VersionListItem,
    VersionSummary,
)
from app.services.flow_simulator import simulate_flow
from app.services.flow_validator import validate_flow_graph

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flows"])


# ===========================================================================
# Helper: fetch flow and verify org ownership
# ===========================================================================

async def _get_flow_or_404(
    flow_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> FlowDefinition:
    result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.id == flow_id,
            FlowDefinition.org_id == org_id,
        )
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


async def _get_draft_version_or_400(
    version_id: uuid.UUID,
    flow_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> FlowVersion:
    """Fetch a version and verify it's a draft (not locked)."""
    result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.id == version_id,
            FlowVersion.flow_id == flow_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.is_locked:
        raise HTTPException(status_code=400, detail="Cannot modify a published/archived version")
    return version


async def _get_version_nodes_edges(
    version_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[list[FlowNode], list[FlowEdge]]:
    """Fetch all nodes and edges for a version."""
    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = edges_result.scalars().all()

    return list(nodes), list(edges)


# ===========================================================================
# Flow CRUD
# ===========================================================================

@router.get("", response_model=PaginatedFlows)
async def list_flows(
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List flows for the current organisation (paginated, filterable)."""
    base = select(FlowDefinition).where(FlowDefinition.org_id == org_id)

    if is_active is None:
        base = base.where(FlowDefinition.is_active == True)
    else:
        base = base.where(FlowDefinition.is_active == is_active)

    if search:
        base = base.where(FlowDefinition.name.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.order_by(FlowDefinition.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedFlows(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=FlowResponse, status_code=201)
async def create_flow(
    body: FlowCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new flow with an auto-created draft version (v1)."""
    # Duplicate name check
    dup = await db.execute(
        select(FlowDefinition.id).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name == body.name,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Flow named '{body.name}' already exists")

    flow = FlowDefinition(
        org_id=org_id,
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        trigger_conditions=body.trigger_conditions,
        max_active_per_lead=body.max_active_per_lead,
        variables=body.variables,
    )
    db.add(flow)
    await db.flush()

    # Auto-create draft version v1
    version = FlowVersion(
        flow_id=flow.id,
        version_number=1,
        status="draft",
    )
    db.add(version)
    await db.commit()
    await db.refresh(flow)
    await db.refresh(version)

    logger.info("flow_created", flow_id=str(flow.id), org_id=str(org_id))

    return FlowResponse(
        id=flow.id,
        org_id=flow.org_id,
        name=flow.name,
        description=flow.description,
        trigger_type=flow.trigger_type,
        trigger_conditions=flow.trigger_conditions,
        max_active_per_lead=flow.max_active_per_lead,
        variables=flow.variables,
        is_active=flow.is_active,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
        current_draft=VersionSummary(
            id=version.id,
            version_number=version.version_number,
            status=version.status,
            is_locked=version.is_locked,
            published_at=version.published_at,
            created_at=version.created_at,
        ),
        current_published=None,
    )


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(
    flow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get flow with current draft and published version summaries."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Fetch draft and published versions
    versions_result = await db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id, FlowVersion.status.in_(["draft", "published"]))
        .order_by(FlowVersion.version_number.desc())
    )
    versions = versions_result.scalars().all()

    draft = next((v for v in versions if v.status == "draft"), None)
    published = next((v for v in versions if v.status == "published"), None)

    def _to_summary(v: FlowVersion | None) -> VersionSummary | None:
        if v is None:
            return None
        return VersionSummary(
            id=v.id, version_number=v.version_number, status=v.status,
            is_locked=v.is_locked, published_at=v.published_at, created_at=v.created_at,
        )

    return FlowResponse(
        id=flow.id, org_id=flow.org_id, name=flow.name, description=flow.description,
        trigger_type=flow.trigger_type, trigger_conditions=flow.trigger_conditions,
        max_active_per_lead=flow.max_active_per_lead, variables=flow.variables,
        is_active=flow.is_active, created_at=flow.created_at, updated_at=flow.updated_at,
        current_draft=_to_summary(draft), current_published=_to_summary(published),
    )


@router.put("/{flow_id}", response_model=FlowListItem)
async def update_flow(
    flow_id: uuid.UUID,
    body: FlowUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update flow metadata (name, description, trigger, etc.)."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    update_data = body.model_dump(exclude_unset=True)

    # Duplicate name check if renaming
    if "name" in update_data and update_data["name"] != flow.name:
        dup = await db.execute(
            select(FlowDefinition.id).where(
                FlowDefinition.org_id == org_id,
                FlowDefinition.name == update_data["name"],
                FlowDefinition.id != flow_id,
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Flow named '{update_data['name']}' already exists")

    for field, value in update_data.items():
        setattr(flow, field, value)

    await db.commit()
    await db.refresh(flow)

    logger.info("flow_updated", flow_id=str(flow_id), fields=list(update_data.keys()))
    return flow


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(
    flow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a flow. Blocked if active instances exist."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Check for active instances
    active_count_result = await db.execute(
        select(func.count()).select_from(
            select(FlowInstance.id).where(
                FlowInstance.flow_id == flow_id,
                FlowInstance.status.in_(["active", "paused"]),
            ).subquery()
        )
    )
    active_count = active_count_result.scalar_one()
    if active_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete flow with {active_count} active/paused instances. Cancel them first.",
        )

    # Soft delete
    flow.is_active = False
    await db.commit()

    logger.info("flow_deleted", flow_id=str(flow_id), org_id=str(org_id))


# ===========================================================================
# Version Management
# ===========================================================================

@router.get("/{flow_id}/versions", response_model=list[VersionListItem])
async def list_versions(
    flow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List all versions for a flow."""
    await _get_flow_or_404(flow_id, org_id, db)

    result = await db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.version_number.desc())
    )
    versions = result.scalars().all()

    items = []
    for v in versions:
        # Count nodes and edges
        node_count = (await db.execute(
            select(func.count()).select_from(
                select(FlowNode.id).where(FlowNode.version_id == v.id).subquery()
            )
        )).scalar_one()
        edge_count = (await db.execute(
            select(func.count()).select_from(
                select(FlowEdge.id).where(FlowEdge.version_id == v.id).subquery()
            )
        )).scalar_one()

        items.append(VersionListItem(
            id=v.id, flow_id=v.flow_id, version_number=v.version_number,
            status=v.status, is_locked=v.is_locked, published_at=v.published_at,
            published_by=v.published_by, created_at=v.created_at,
            node_count=node_count, edge_count=edge_count,
        ))

    return items


@router.get("/{flow_id}/versions/{version_id}", response_model=VersionDetailResponse)
async def get_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get version with all nodes and edges."""
    await _get_flow_or_404(flow_id, org_id, db)

    result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.id == version_id,
            FlowVersion.flow_id == flow_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    nodes, edges = await _get_version_nodes_edges(version_id, db)

    return VersionDetailResponse(
        id=version.id, flow_id=version.flow_id, version_number=version.version_number,
        status=version.status, is_locked=version.is_locked, published_at=version.published_at,
        published_by=version.published_by, created_at=version.created_at,
        nodes=nodes, edges=edges,
    )


@router.post("/{flow_id}/versions", response_model=VersionDetailResponse, status_code=201)
async def create_version(
    flow_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new draft version, copying nodes/edges from the current published version."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Check no existing draft
    existing_draft = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.status == "draft",
        )
    )
    if existing_draft.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A draft version already exists. Publish or delete it first.")

    # Get latest version number
    max_version_result = await db.execute(
        select(func.max(FlowVersion.version_number)).where(FlowVersion.flow_id == flow_id)
    )
    max_version = max_version_result.scalar_one() or 0

    new_version = FlowVersion(
        flow_id=flow_id,
        version_number=max_version + 1,
        status="draft",
    )
    db.add(new_version)
    await db.flush()

    # Copy nodes and edges from published version
    published_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.status == "published",
        )
    )
    published = published_result.scalar_one_or_none()

    if published:
        old_nodes, old_edges = await _get_version_nodes_edges(published.id, db)

        # Map old node IDs to new node IDs
        node_id_map: dict[uuid.UUID, uuid.UUID] = {}

        for old_node in old_nodes:
            new_node_id = uuid.uuid4()
            node_id_map[old_node.id] = new_node_id
            new_node = FlowNode(
                id=new_node_id,
                version_id=new_version.id,
                org_id=org_id,
                node_type=old_node.node_type,
                name=old_node.name,
                position_x=old_node.position_x,
                position_y=old_node.position_y,
                config=old_node.config,
            )
            db.add(new_node)

        for old_edge in old_edges:
            new_edge = FlowEdge(
                version_id=new_version.id,
                org_id=org_id,
                source_node_id=node_id_map.get(old_edge.source_node_id, old_edge.source_node_id),
                target_node_id=node_id_map.get(old_edge.target_node_id, old_edge.target_node_id),
                condition_label=old_edge.condition_label,
                sort_order=old_edge.sort_order,
            )
            db.add(new_edge)

    await db.commit()
    await db.refresh(new_version)

    nodes, edges = await _get_version_nodes_edges(new_version.id, db)

    logger.info("version_created", flow_id=str(flow_id), version=new_version.version_number)

    return VersionDetailResponse(
        id=new_version.id, flow_id=new_version.flow_id,
        version_number=new_version.version_number, status=new_version.status,
        is_locked=new_version.is_locked, published_at=new_version.published_at,
        published_by=new_version.published_by, created_at=new_version.created_at,
        nodes=nodes, edges=edges,
    )


@router.post("/{flow_id}/versions/{version_id}/publish", response_model=PublishResponse)
async def publish_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Validate and publish a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft versions can be published")

    # Run validation
    nodes, edges = await _get_version_nodes_edges(version_id, db)
    node_dicts = [
        {"id": n.id, "node_type": n.node_type, "name": n.name, "config": n.config}
        for n in nodes
    ]
    edge_dicts = [
        {"id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
         "condition_label": e.condition_label, "sort_order": e.sort_order}
        for e in edges
    ]
    validation = validate_flow_graph(node_dicts, edge_dicts)

    if not validation.valid:
        return PublishResponse(
            version=VersionSummary(
                id=version.id, version_number=version.version_number, status=version.status,
                is_locked=version.is_locked, published_at=version.published_at,
                created_at=version.created_at,
            ),
            validation=validation,
        )

    # Archive current published version
    await db.execute(
        sa_update(FlowVersion)
        .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "published")
        .values(status="archived")
    )

    # Publish this version
    now = datetime.now(timezone.utc)
    version.status = "published"
    version.is_locked = True
    version.published_at = now
    version.published_by = user.id

    await db.commit()
    await db.refresh(version)

    logger.info("version_published", flow_id=str(flow_id), version=version.version_number)

    return PublishResponse(
        version=VersionSummary(
            id=version.id, version_number=version.version_number, status=version.status,
            is_locked=version.is_locked, published_at=version.published_at,
            created_at=version.created_at,
        ),
        validation=validation,
    )


@router.post("/{flow_id}/clone", response_model=FlowResponse, status_code=201)
async def clone_flow(
    flow_id: uuid.UUID,
    body: CloneRequest = CloneRequest(),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate a flow with all its nodes/edges from the published (or latest) version."""
    source_flow = await _get_flow_or_404(flow_id, org_id, db)

    clone_name = body.name or f"{source_flow.name} (Copy)"

    # Check name uniqueness
    dup = await db.execute(
        select(FlowDefinition.id).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name == clone_name,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Flow named '{clone_name}' already exists")

    # Create new flow
    new_flow = FlowDefinition(
        org_id=org_id,
        name=clone_name,
        description=source_flow.description,
        trigger_type=source_flow.trigger_type,
        trigger_conditions=source_flow.trigger_conditions,
        max_active_per_lead=source_flow.max_active_per_lead,
        variables=source_flow.variables,
    )
    db.add(new_flow)
    await db.flush()

    # Find source version to copy (prefer published, fallback to latest)
    source_version_result = await db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(
            # Prefer published
            (FlowVersion.status == "published").desc(),
            FlowVersion.version_number.desc(),
        )
        .limit(1)
    )
    source_version = source_version_result.scalar_one_or_none()

    new_version = FlowVersion(
        flow_id=new_flow.id,
        version_number=1,
        status="draft",
    )
    db.add(new_version)
    await db.flush()

    if source_version:
        old_nodes, old_edges = await _get_version_nodes_edges(source_version.id, db)
        node_id_map: dict[uuid.UUID, uuid.UUID] = {}

        for old_node in old_nodes:
            new_id = uuid.uuid4()
            node_id_map[old_node.id] = new_id
            db.add(FlowNode(
                id=new_id, version_id=new_version.id, org_id=org_id,
                node_type=old_node.node_type, name=old_node.name,
                position_x=old_node.position_x, position_y=old_node.position_y,
                config=old_node.config,
            ))

        for old_edge in old_edges:
            db.add(FlowEdge(
                version_id=new_version.id, org_id=org_id,
                source_node_id=node_id_map.get(old_edge.source_node_id, old_edge.source_node_id),
                target_node_id=node_id_map.get(old_edge.target_node_id, old_edge.target_node_id),
                condition_label=old_edge.condition_label, sort_order=old_edge.sort_order,
            ))

    await db.commit()
    await db.refresh(new_flow)
    await db.refresh(new_version)

    logger.info("flow_cloned", source_id=str(flow_id), new_id=str(new_flow.id))

    return FlowResponse(
        id=new_flow.id, org_id=new_flow.org_id, name=new_flow.name,
        description=new_flow.description, trigger_type=new_flow.trigger_type,
        trigger_conditions=new_flow.trigger_conditions,
        max_active_per_lead=new_flow.max_active_per_lead, variables=new_flow.variables,
        is_active=new_flow.is_active, created_at=new_flow.created_at,
        updated_at=new_flow.updated_at,
        current_draft=VersionSummary(
            id=new_version.id, version_number=new_version.version_number,
            status=new_version.status, is_locked=new_version.is_locked,
            published_at=new_version.published_at, created_at=new_version.created_at,
        ),
        current_published=None,
    )


# ===========================================================================
# Atomic Graph Save
# ===========================================================================

@router.put("/{flow_id}/versions/{version_id}", response_model=GraphSaveResponse)
async def save_graph(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: GraphSaveRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Atomic graph save: replaces ALL nodes and edges in a draft version.

    This is the primary save mechanism for the canvas. Accepts the full
    {nodes, edges} payload and replaces everything in a single transaction.
    """
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    # Delete existing nodes and edges
    await db.execute(
        sa_delete(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    await db.execute(
        sa_delete(FlowNode).where(FlowNode.version_id == version_id)
    )

    # Insert new nodes
    node_id_map: dict[str, str] = {}  # client temp ID → server UUID
    server_node_ids: dict[str, uuid.UUID] = {}  # client temp ID → UUID for edge mapping

    for node_input in body.nodes:
        if node_input.id is not None:
            new_id = node_input.id
        else:
            new_id = uuid.uuid4()
            # Track temp IDs for the response
            node_id_map[str(node_input.id) if node_input.id else str(new_id)] = str(new_id)

        server_node_ids[str(node_input.id) if node_input.id else str(new_id)] = new_id

        db.add(FlowNode(
            id=new_id,
            version_id=version_id,
            org_id=org_id,
            node_type=node_input.node_type,
            name=node_input.name,
            position_x=node_input.position_x,
            position_y=node_input.position_y,
            config=node_input.config,
        ))

    # Insert new edges
    for edge_input in body.edges:
        edge_id = edge_input.id or uuid.uuid4()
        db.add(FlowEdge(
            id=edge_id,
            version_id=version_id,
            org_id=org_id,
            source_node_id=edge_input.source_node_id,
            target_node_id=edge_input.target_node_id,
            condition_label=edge_input.condition_label,
            sort_order=edge_input.sort_order,
        ))

    await db.commit()

    # Fetch the saved state
    nodes, edges = await _get_version_nodes_edges(version_id, db)

    logger.info(
        "graph_saved",
        flow_id=str(flow_id), version_id=str(version_id),
        node_count=len(nodes), edge_count=len(edges),
    )

    return GraphSaveResponse(
        version=VersionDetailResponse(
            id=version.id, flow_id=version.flow_id,
            version_number=version.version_number, status=version.status,
            is_locked=version.is_locked, published_at=version.published_at,
            published_by=version.published_by, created_at=version.created_at,
            nodes=nodes, edges=edges,
        ),
        node_id_map=node_id_map,
    )


# ===========================================================================
# Individual Node/Edge CRUD (for granular edits on draft versions)
# ===========================================================================

@router.post("/{flow_id}/versions/{version_id}/nodes", response_model=NodeResponse, status_code=201)
async def add_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: NodeCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Add a single node to a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    node = FlowNode(
        version_id=version_id,
        org_id=org_id,
        node_type=body.node_type,
        name=body.name,
        position_x=body.position_x,
        position_y=body.position_y,
        config=body.config,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)

    logger.info("node_added", node_id=str(node.id), version_id=str(version_id))
    return node


@router.put("/{flow_id}/versions/{version_id}/nodes/{node_id}", response_model=NodeResponse)
async def update_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    node_id: uuid.UUID,
    body: NodeUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update a single node in a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    result = await db.execute(
        select(FlowNode).where(
            FlowNode.id == node_id,
            FlowNode.version_id == version_id,
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(node, field, value)

    await db.commit()
    await db.refresh(node)

    logger.info("node_updated", node_id=str(node_id), fields=list(update_data.keys()))
    return node


@router.delete("/{flow_id}/versions/{version_id}/nodes/{node_id}", status_code=204)
async def delete_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    node_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a node and its connected edges from a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    result = await db.execute(
        select(FlowNode).where(FlowNode.id == node_id, FlowNode.version_id == version_id)
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    # Delete connected edges first
    await db.execute(
        sa_delete(FlowEdge).where(
            FlowEdge.version_id == version_id,
            (FlowEdge.source_node_id == node_id) | (FlowEdge.target_node_id == node_id),
        )
    )

    await db.execute(
        sa_delete(FlowNode).where(FlowNode.id == node_id)
    )

    await db.commit()
    logger.info("node_deleted", node_id=str(node_id), version_id=str(version_id))


@router.post("/{flow_id}/versions/{version_id}/edges", response_model=EdgeResponse, status_code=201)
async def add_edge(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: EdgeCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Add a single edge to a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    # Verify source and target nodes exist in this version
    for nid, label in [(body.source_node_id, "source"), (body.target_node_id, "target")]:
        check = await db.execute(
            select(FlowNode.id).where(FlowNode.id == nid, FlowNode.version_id == version_id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail=f"Edge {label} node {nid} not found in this version")

    edge = FlowEdge(
        version_id=version_id,
        org_id=org_id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        condition_label=body.condition_label,
        sort_order=body.sort_order,
    )
    db.add(edge)
    await db.commit()
    await db.refresh(edge)

    logger.info("edge_added", edge_id=str(edge.id), version_id=str(version_id))
    return edge


@router.delete("/{flow_id}/versions/{version_id}/edges/{edge_id}", status_code=204)
async def delete_edge(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    edge_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single edge from a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    result = await db.execute(
        select(FlowEdge).where(FlowEdge.id == edge_id, FlowEdge.version_id == version_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    await db.execute(sa_delete(FlowEdge).where(FlowEdge.id == edge_id))
    await db.commit()

    logger.info("edge_deleted", edge_id=str(edge_id), version_id=str(version_id))


@router.put("/{flow_id}/versions/{version_id}/layout", status_code=200)
async def update_layout(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: BulkLayoutUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Bulk update node positions (layout changes from canvas drag)."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_draft_version_or_400(version_id, flow_id, org_id, db)

    for pos in body.positions:
        await db.execute(
            sa_update(FlowNode)
            .where(FlowNode.id == pos.node_id, FlowNode.version_id == version_id)
            .values(position_x=pos.position_x, position_y=pos.position_y)
        )

    await db.commit()

    logger.info("layout_updated", version_id=str(version_id), node_count=len(body.positions))
    return {"updated": len(body.positions)}


# ===========================================================================
# Validation (without publishing)
# ===========================================================================

@router.post("/{flow_id}/versions/{version_id}/validate", response_model=ValidationResult)
async def validate_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Run validation on a version without publishing."""
    await _get_flow_or_404(flow_id, org_id, db)

    result = await db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    nodes, edges = await _get_version_nodes_edges(version_id, db)
    node_dicts = [
        {"id": n.id, "node_type": n.node_type, "name": n.name, "config": n.config}
        for n in nodes
    ]
    edge_dicts = [
        {"id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
         "condition_label": e.condition_label, "sort_order": e.sort_order}
        for e in edges
    ]

    return validate_flow_graph(node_dicts, edge_dicts)


# ===========================================================================
# Simulation (Dry-Run)
# ===========================================================================

@router.post("/{flow_id}/versions/{version_id}/simulate", response_model=SimulationResult)
async def simulate_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: SimulationRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run simulation: walks the graph with mock lead data and pre-set outcomes."""
    await _get_flow_or_404(flow_id, org_id, db)

    result = await db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Version not found")

    nodes, edges = await _get_version_nodes_edges(version_id, db)
    node_dicts = [
        {"id": n.id, "node_type": n.node_type, "name": n.name, "config": n.config}
        for n in nodes
    ]
    edge_dicts = [
        {"id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
         "condition_label": e.condition_label, "sort_order": e.sort_order}
        for e in edges
    ]

    return simulate_flow(
        nodes=node_dicts,
        edges=edge_dicts,
        mock_lead=body.mock_lead,
        outcomes=body.outcomes,
    )


# ===========================================================================
# Live Test
# ===========================================================================

@router.post("/{flow_id}/live-test", response_model=LiveTestResponse, status_code=201)
async def start_live_test(
    flow_id: uuid.UUID,
    body: LiveTestRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Start a live test: creates a real FlowInstance with is_test=true and delay compression."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Find published version
    pub_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.status == "published",
        )
    )
    published = pub_result.scalar_one_or_none()
    if published is None:
        raise HTTPException(status_code=400, detail="No published version to test. Publish the flow first.")

    # Find the entry node
    nodes, edges = await _get_version_nodes_edges(published.id, db)
    incoming_targets = {e.target_node_id for e in edges}
    entry_nodes = [n for n in nodes if n.id not in incoming_targets]

    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Published version has no entry node")

    # Create test instance
    instance = FlowInstance(
        org_id=org_id,
        flow_id=flow_id,
        version_id=published.id,
        lead_id=None,  # Test instances may not have a real lead
        status="active",
        current_node_id=entry_nodes[0].id,
        context_data={
            **body.context_data,
            "test_phone": body.phone_number,
            "delay_compression_ratio": body.delay_compression_ratio,
        },
        is_test=True,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    logger.info(
        "live_test_started",
        flow_id=str(flow_id), instance_id=str(instance.id),
        phone=body.phone_number,
    )

    return LiveTestResponse(
        instance_id=instance.id,
        message=f"Live test started on v{published.version_number}. Calls/messages will go to {body.phone_number}.",
    )


# ===========================================================================
# Instance Management
# ===========================================================================

@router.get("/{flow_id}/instances", response_model=PaginatedFlowInstances)
async def list_instances(
    flow_id: uuid.UUID,
    lead_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    is_test: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List instances for a flow with optional filtering."""
    await _get_flow_or_404(flow_id, org_id, db)

    base = select(FlowInstance).where(
        FlowInstance.flow_id == flow_id,
        FlowInstance.org_id == org_id,
    )

    if lead_id:
        base = base.where(FlowInstance.lead_id == lead_id)
    if status:
        base = base.where(FlowInstance.status == status)
    if is_test is not None:
        base = base.where(FlowInstance.is_test == is_test)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.order_by(FlowInstance.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedFlowInstances(items=items, total=total, page=page, page_size=page_size)


@router.get("/instances/{instance_id}", response_model=FlowInstanceDetailResponse)
async def get_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get instance detail with touchpoints and transitions."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.org_id == org_id,
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    tp_result = await db.execute(
        select(FlowTouchpoint)
        .where(FlowTouchpoint.instance_id == instance_id)
        .order_by(FlowTouchpoint.scheduled_at)
    )
    touchpoints = tp_result.scalars().all()

    tr_result = await db.execute(
        select(FlowTransition)
        .where(FlowTransition.instance_id == instance_id)
        .order_by(FlowTransition.transitioned_at)
    )
    transitions = tr_result.scalars().all()

    return FlowInstanceDetailResponse(
        id=instance.id, org_id=instance.org_id, flow_id=instance.flow_id,
        version_id=instance.version_id, lead_id=instance.lead_id,
        trigger_call_id=instance.trigger_call_id, status=instance.status,
        current_node_id=instance.current_node_id, context_data=instance.context_data,
        error_message=instance.error_message, is_test=instance.is_test,
        started_at=instance.started_at, completed_at=instance.completed_at,
        created_at=instance.created_at, updated_at=instance.updated_at,
        touchpoints=touchpoints, transitions=transitions,
    )


@router.post("/{flow_id}/enroll", response_model=EnrollResponse, status_code=201)
async def enroll_leads(
    flow_id: uuid.UUID,
    body: EnrollRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Enroll one or more leads into the flow on the current published version."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    if not flow.is_active:
        raise HTTPException(status_code=400, detail="Cannot enroll into an inactive flow")

    # Find published version
    pub_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.status == "published",
        )
    )
    published = pub_result.scalar_one_or_none()
    if published is None:
        raise HTTPException(status_code=400, detail="No published version. Publish the flow first.")

    # Find entry node
    nodes, edges = await _get_version_nodes_edges(published.id, db)
    incoming_targets = {e.target_node_id for e in edges}
    entry_nodes = [n for n in nodes if n.id not in incoming_targets]
    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Published version has no entry node")

    entry_node_id = entry_nodes[0].id
    enrolled: list[uuid.UUID] = []
    skipped: list[SkippedLead] = []

    for lead_id in body.lead_ids:
        # Check max_active_per_lead
        active_count_result = await db.execute(
            select(func.count()).select_from(
                select(FlowInstance.id).where(
                    FlowInstance.flow_id == flow_id,
                    FlowInstance.lead_id == lead_id,
                    FlowInstance.status.in_(["active", "paused"]),
                ).subquery()
            )
        )
        active_count = active_count_result.scalar_one()

        if active_count >= flow.max_active_per_lead:
            skipped.append(SkippedLead(
                lead_id=lead_id,
                reason=f"Already has {active_count} active instance(s) (max: {flow.max_active_per_lead})",
            ))
            continue

        instance = FlowInstance(
            org_id=org_id,
            flow_id=flow_id,
            version_id=published.id,
            lead_id=lead_id,
            status="active",
            current_node_id=entry_node_id,
            context_data=body.context_data,
            is_test=False,
        )
        db.add(instance)
        enrolled.append(lead_id)

    await db.commit()

    logger.info(
        "leads_enrolled",
        flow_id=str(flow_id), enrolled=len(enrolled), skipped=len(skipped),
    )

    return EnrollResponse(enrolled=enrolled, skipped=skipped)


@router.post("/instances/{instance_id}/cancel", status_code=200)
async def cancel_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an active or paused instance."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.org_id == org_id,
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    if instance.status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel instance with status '{instance.status}'")

    instance.status = "cancelled"
    instance.completed_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("instance_cancelled", instance_id=str(instance_id))
    return {"status": "cancelled"}


@router.post("/instances/{instance_id}/pause", status_code=200)
async def pause_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Pause an active instance."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.org_id == org_id,
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    if instance.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot pause instance with status '{instance.status}'")

    instance.status = "paused"
    await db.commit()

    logger.info("instance_paused", instance_id=str(instance_id))
    return {"status": "paused"}


@router.post("/instances/{instance_id}/resume", status_code=200)
async def resume_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused instance."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.org_id == org_id,
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    if instance.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume instance with status '{instance.status}'")

    instance.status = "active"
    await db.commit()

    logger.info("instance_resumed", instance_id=str(instance_id))
    return {"status": "active"}


@router.post("/instances/{instance_id}/reenroll", response_model=FlowInstanceListItem, status_code=201)
async def reenroll_instance(
    instance_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel current instance and re-enroll the lead on the latest published version."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.org_id == org_id,
        )
    )
    old_instance = result.scalar_one_or_none()
    if old_instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Cancel old instance
    if old_instance.status in ("active", "paused"):
        old_instance.status = "cancelled"
        old_instance.completed_at = datetime.now(timezone.utc)

    # Find latest published version
    pub_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == old_instance.flow_id,
            FlowVersion.status == "published",
        )
    )
    published = pub_result.scalar_one_or_none()
    if published is None:
        raise HTTPException(status_code=400, detail="No published version available for re-enrollment")

    # Find entry node
    nodes, edges = await _get_version_nodes_edges(published.id, db)
    incoming_targets = {e.target_node_id for e in edges}
    entry_nodes = [n for n in nodes if n.id not in incoming_targets]
    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Published version has no entry node")

    new_instance = FlowInstance(
        org_id=org_id,
        flow_id=old_instance.flow_id,
        version_id=published.id,
        lead_id=old_instance.lead_id,
        status="active",
        current_node_id=entry_nodes[0].id,
        context_data=old_instance.context_data,
        is_test=old_instance.is_test,
    )
    db.add(new_instance)
    await db.commit()
    await db.refresh(new_instance)

    logger.info(
        "instance_reenrolled",
        old_id=str(instance_id), new_id=str(new_instance.id),
        version=published.version_number,
    )

    return new_instance
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_flows_api.py -v
```

Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/api/flows.py tests/test_flows_api.py
git commit -m "feat: add flow builder API — CRUD, versions, graph save, instances

Complete REST API for flow builder with FastAPI. Includes:
- Flow CRUD (list/create/get/update/delete)
- Version management (create draft, get with nodes/edges, publish, clone)
- Atomic graph save (PUT replaces all nodes/edges in single tx)
- Individual node/edge CRUD for draft versions
- Instance management (enroll, cancel, pause, resume, re-enroll)
- Validation and simulation endpoints
- Live test endpoint with delay compression"
```

---

## Task 5: Graph Save & Node/Edge Tests

**Files:**
- Create: `tests/test_flows_graph_api.py`

- [ ] **Step 1: Write tests for atomic graph save and node/edge CRUD**

```python
# tests/test_flows_graph_api.py
"""Tests for atomic graph save and individual node/edge CRUD."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.org_id = uuid.uuid4()
    user.role = "client_admin"
    user.status = "active"
    return user


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def auth_overrides(mock_user, mock_db):
    from app.auth.dependencies import get_current_user, get_current_org
    from app.database import get_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_org] = lambda: mock_user.org_id
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


class TestAtomicGraphSave:

    @pytest.mark.asyncio
    async def test_save_rejects_locked_version(self, auth_overrides, mock_db):
        """PUT /api/flows/{id}/versions/{vid} rejects published versions."""
        flow_id = uuid.uuid4()
        version_id = uuid.uuid4()

        # Mock flow lookup → found
        flow_mock = MagicMock()
        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = flow_mock

        # Mock version lookup → locked
        version_mock = MagicMock()
        version_mock.is_locked = True
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version_mock

        mock_db.execute = AsyncMock(side_effect=[flow_result, version_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/flows/{flow_id}/versions/{version_id}",
                json={"nodes": [], "edges": []},
            )

        assert resp.status_code == 400
        assert "published" in resp.json()["detail"].lower() or "modify" in resp.json()["detail"].lower()


class TestNodeCRUD:

    @pytest.mark.asyncio
    async def test_add_node_to_locked_version_fails(self, auth_overrides, mock_db):
        """POST .../nodes rejects if version is locked."""
        flow_id = uuid.uuid4()
        version_id = uuid.uuid4()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = MagicMock()

        version_mock = MagicMock()
        version_mock.is_locked = True
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version_mock

        mock_db.execute = AsyncMock(side_effect=[flow_result, version_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/flows/{flow_id}/versions/{version_id}/nodes",
                json={"node_type": "voice_call", "name": "Test"},
            )

        assert resp.status_code == 400


class TestEdgeCRUD:

    @pytest.mark.asyncio
    async def test_add_edge_invalid_source_fails(self, auth_overrides, mock_db):
        """POST .../edges fails if source node not in version."""
        flow_id = uuid.uuid4()
        version_id = uuid.uuid4()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = MagicMock()

        version_mock = MagicMock()
        version_mock.is_locked = False
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version_mock

        # Source node not found
        source_check = MagicMock()
        source_check.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[flow_result, version_result, source_check])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/flows/{flow_id}/versions/{version_id}/edges",
                json={
                    "source_node_id": str(uuid.uuid4()),
                    "target_node_id": str(uuid.uuid4()),
                },
            )

        assert resp.status_code == 400
        assert "source" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_flows_graph_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_flows_graph_api.py
git commit -m "test: add tests for atomic graph save and node/edge CRUD

Verifies locked version rejection, edge source validation,
and draft-only mutation enforcement."
```

---

## Task 6: Instance Management Tests

**Files:**
- Create: `tests/test_flows_instances_api.py`

- [ ] **Step 1: Write tests for instance endpoints**

```python
# tests/test_flows_instances_api.py
"""Tests for flow instance management endpoints."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.org_id = uuid.uuid4()
    user.role = "client_admin"
    user.status = "active"
    return user


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def auth_overrides(mock_user, mock_db):
    from app.auth.dependencies import get_current_user, get_current_org
    from app.database import get_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_org] = lambda: mock_user.org_id
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


class TestEnroll:

    @pytest.mark.asyncio
    async def test_enroll_no_published_version(self, auth_overrides, mock_db):
        """POST /api/flows/{id}/enroll fails without published version."""
        flow_id = uuid.uuid4()

        flow_mock = MagicMock()
        flow_mock.is_active = True
        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = flow_mock

        # No published version
        pub_result = MagicMock()
        pub_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[flow_result, pub_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/flows/{flow_id}/enroll",
                json={"lead_ids": [str(uuid.uuid4())]},
            )

        assert resp.status_code == 400
        assert "published" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_enroll_inactive_flow_rejected(self, auth_overrides, mock_db):
        """POST /api/flows/{id}/enroll rejected for inactive flow."""
        flow_id = uuid.uuid4()

        flow_mock = MagicMock()
        flow_mock.is_active = False
        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = flow_mock

        mock_db.execute = AsyncMock(return_value=flow_result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/flows/{flow_id}/enroll",
                json={"lead_ids": [str(uuid.uuid4())]},
            )

        assert resp.status_code == 400
        assert "inactive" in resp.json()["detail"].lower()


class TestInstanceStateTransitions:

    @pytest.mark.asyncio
    async def test_pause_non_active_fails(self, auth_overrides, mock_db):
        """POST /instances/{id}/pause fails if not active."""
        instance_id = uuid.uuid4()

        instance_mock = MagicMock()
        instance_mock.status = "completed"
        result = MagicMock()
        result.scalar_one_or_none.return_value = instance_mock

        mock_db.execute = AsyncMock(return_value=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/flows/instances/{instance_id}/pause")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_resume_non_paused_fails(self, auth_overrides, mock_db):
        """POST /instances/{id}/resume fails if not paused."""
        instance_id = uuid.uuid4()

        instance_mock = MagicMock()
        instance_mock.status = "active"
        result = MagicMock()
        result.scalar_one_or_none.return_value = instance_mock

        mock_db.execute = AsyncMock(return_value=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/flows/instances/{instance_id}/resume")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_completed_fails(self, auth_overrides, mock_db):
        """POST /instances/{id}/cancel fails on completed instance."""
        instance_id = uuid.uuid4()

        instance_mock = MagicMock()
        instance_mock.status = "completed"
        result = MagicMock()
        result.scalar_one_or_none.return_value = instance_mock

        mock_db.execute = AsyncMock(return_value=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/flows/instances/{instance_id}/cancel")

        assert resp.status_code == 400


class TestLiveTest:

    @pytest.mark.asyncio
    async def test_live_test_no_published_version(self, auth_overrides, mock_db):
        """POST /api/flows/{id}/live-test fails without published version."""
        flow_id = uuid.uuid4()

        flow_mock = MagicMock()
        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = flow_mock

        pub_result = MagicMock()
        pub_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[flow_result, pub_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/flows/{flow_id}/live-test",
                json={"phone_number": "+1234567890"},
            )

        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_flows_instances_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_flows_instances_api.py
git commit -m "test: add tests for flow instance management endpoints

Covers enrollment without published version, inactive flow rejection,
state transition enforcement (pause/resume/cancel), and live test
without published version."
```

---

## Task 7: Wire Router into Main App

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add the flows router import and registration**

In `app/main.py`, add to the imports section (near existing `from app.api import ...`):

```python
# Add 'flows' to the existing import line:
from app.api import admin, analytics, billing, bots, calls, campaigns, flows, health, leads, messaging_providers, payments, queue, sequence_analytics, sequences, telephony, webhook, webhooks
```

In the "Mount routers" section, add after `app.include_router(sequences.router)`:

```python
app.include_router(flows.router)
```

- [ ] **Step 2: Verify app starts**

```bash
python -c "from app.main import app; print(f'Routes: {len(app.routes)}')"
```

Expected: No import errors, route count increases.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --timeout=30
```

Expected: No regressions.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: register flow builder API router in main app

Adds /api/flows/* endpoints to the FastAPI app."
```

---

## Summary

| Task | What it does | Files |
|------|-------------|-------|
| 1 | Pydantic request/response schemas | `app/schemas/flow.py` |
| 2 | Flow graph validation service | `app/services/flow_validator.py`, tests |
| 3 | Flow simulation (dry-run) engine | `app/services/flow_simulator.py`, tests |
| 4 | Flow API router (all endpoints) | `app/api/flows.py`, tests |
| 5 | Graph save + node/edge tests | tests |
| 6 | Instance management tests | tests |
| 7 | Wire router into main app | `app/main.py` |

**Total:** 7 tasks, ~28 steps, 7 commits.

**Endpoint count:** 27 endpoints total:
- 5 Flow CRUD (`GET/POST/GET/PUT/DELETE`)
- 6 Version management (`GET list`, `GET detail`, `POST create`, `PUT graph save`, `POST publish`, `POST clone`)
- 6 Node/Edge CRUD (`POST/PUT/DELETE node`, `POST/DELETE edge`, `PUT layout`)
- 2 Validation + Simulation (`POST validate`, `POST simulate`)
- 1 Live test (`POST live-test`)
- 7 Instance management (`GET list`, `GET detail`, `POST enroll`, `POST cancel/pause/resume/reenroll`)

After completing this plan, proceed to **Plan 4: Flow Engine** (graph traversal, scheduler integration, event processing).
