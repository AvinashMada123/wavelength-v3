"""Pydantic request/response schemas for the flow builder API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Flow Definition
# ---------------------------------------------------------------------------


class FlowCreate(BaseModel):
    name: str
    description: str | None = None
    trigger_type: str = "manual"
    trigger_conditions: dict | None = None
    max_active_per_lead: int = 1
    variables: dict | None = None


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_conditions: dict | None = None
    max_active_per_lead: int | None = None
    is_active: bool | None = None


class FlowResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_conditions: dict | None
    max_active_per_lead: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    current_version: FlowVersionResponse | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Flow Version
# ---------------------------------------------------------------------------


class FlowVersionResponse(BaseModel):
    id: UUID
    flow_id: UUID
    version_number: int
    status: str
    is_locked: bool
    published_at: datetime | None
    created_at: datetime
    nodes: list[FlowNodeResponse] = []
    edges: list[FlowEdgeResponse] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Nodes & Edges
# ---------------------------------------------------------------------------


class FlowNodeCreate(BaseModel):
    id: UUID | None = None
    node_type: str
    name: str
    position_x: float = 0
    position_y: float = 0
    config: dict = Field(default_factory=dict)


class FlowNodeResponse(BaseModel):
    id: UUID
    version_id: UUID
    node_type: str
    name: str
    position_x: float
    position_y: float
    config: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class FlowEdgeCreate(BaseModel):
    source_node_id: UUID
    target_node_id: UUID
    condition_label: str = "default"
    sort_order: int = 0


class FlowEdgeResponse(BaseModel):
    id: UUID
    version_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    condition_label: str
    sort_order: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Atomic graph save
# ---------------------------------------------------------------------------


class GraphSaveRequest(BaseModel):
    nodes: list[FlowNodeCreate]
    edges: list[FlowEdgeCreate]


# ---------------------------------------------------------------------------
# Instance / Enrollment
# ---------------------------------------------------------------------------


class FlowEnrollRequest(BaseModel):
    lead_ids: list[UUID]
    context_data: dict | None = None


class FlowInstanceResponse(BaseModel):
    id: UUID
    flow_id: UUID
    version_id: UUID
    lead_id: UUID
    status: str
    current_node_id: UUID | None
    context_data: dict | None
    is_test: bool
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class SimulateRequest(BaseModel):
    mock_lead: dict
    outcomes: dict[str, str]  # node_id -> outcome label


class SimulateResponse(BaseModel):
    path: list[dict]
    goals_hit: list[str]
    end_reason: str | None


# ---------------------------------------------------------------------------
# Live test
# ---------------------------------------------------------------------------


class LiveTestRequest(BaseModel):
    phone_number: str
    delay_compression: float = 60.0  # 1 hour compressed to 1 minute


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    valid: bool
    errors: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
