"""REST API for flow builder — definitions, versions, nodes, edges, instances, and simulation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
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
    FlowCreate,
    FlowEnrollRequest,
    FlowInstanceResponse,
    FlowResponse,
    FlowUpdate,
    FlowVersionResponse,
    GraphSaveRequest,
    LiveTestRequest,
    SimulateRequest,
    SimulateResponse,
    ValidationResult,
)
from app.services.flow_export import export_flow_version, import_flow
from app.services.flow_simulator import simulate_flow
from app.services.flow_validator import validate_flow

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flows"])


# ---------------------------------------------------------------------------
# Pydantic schemas (inline for pagination / list items)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, ConfigDict, Field


class FlowListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    trigger_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedFlows(BaseModel):
    items: list[FlowListItem]
    total: int
    page: int
    page_size: int


class VersionListItem(BaseModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    version_number: int
    status: str
    is_locked: bool
    published_at: datetime | None
    published_by: uuid.UUID | None
    created_at: datetime

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
    condition_label: str
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


class InstanceListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    flow_id: uuid.UUID
    version_id: uuid.UUID
    lead_id: uuid.UUID
    status: str
    current_node_id: uuid.UUID | None
    is_test: bool
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedInstances(BaseModel):
    items: list[InstanceListItem]
    total: int
    page: int
    page_size: int


class TouchpointResponse(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    node_id: uuid.UUID
    org_id: uuid.UUID
    lead_id: uuid.UUID | None
    status: str
    scheduled_at: datetime
    executed_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    generated_content: str | None
    error_message: str | None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransitionResponse(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    edge_id: uuid.UUID | None
    outcome_data: dict[str, Any] | None
    transitioned_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InstanceDetailResponse(BaseModel):
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
    touchpoints: list[TouchpointResponse] = Field(default_factory=list)
    transitions: list[TransitionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class NodeCreate(BaseModel):
    node_type: str
    name: str
    position_x: float = 0
    position_y: float = 0
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeCreate(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    condition_label: str
    sort_order: int = 0


class LayoutUpdate(BaseModel):
    node_id: uuid.UUID
    position_x: float
    position_y: float


class BulkLayoutRequest(BaseModel):
    positions: list[LayoutUpdate]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_flow_or_404(
    flow_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession
) -> FlowDefinition:
    """Fetch a FlowDefinition scoped to org, or raise 404."""
    result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.id == flow_id, FlowDefinition.org_id == org_id
        )
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")
    return flow


async def _get_version_or_404(
    version_id: uuid.UUID, flow_id: uuid.UUID, db: AsyncSession
) -> FlowVersion:
    """Fetch a FlowVersion belonging to the given flow, or raise 404."""
    result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.id == version_id, FlowVersion.flow_id == flow_id
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return version


async def _get_instance_or_404(
    instance_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession
) -> FlowInstance:
    """Fetch a FlowInstance scoped to org, or raise 404."""
    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id, FlowInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return instance


def _require_draft(version: FlowVersion) -> None:
    """Raise 409 if the version is not a draft."""
    if version.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version is '{version.status}', not draft. Only draft versions can be edited.",
        )


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedFlows)
async def list_flows(
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List flows for the current organisation."""
    base = select(FlowDefinition).where(FlowDefinition.org_id == org_id)

    if is_active is None:
        base = base.where(FlowDefinition.is_active == True)  # noqa: E712
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


@router.post("", response_model=FlowListItem, status_code=status.HTTP_201_CREATED)
async def create_flow(
    body: FlowCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new flow definition and auto-create a draft v1."""
    # Duplicate name check
    dup = await db.execute(
        select(FlowDefinition.id).where(
            FlowDefinition.org_id == org_id, FlowDefinition.name == body.name
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Flow named '{body.name}' already exists",
        )

    flow = FlowDefinition(
        org_id=org_id,
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        trigger_conditions=body.trigger_conditions if body.trigger_conditions else {},
        max_active_per_lead=body.max_active_per_lead if body.max_active_per_lead else 1,
        variables=body.variables if body.variables else [],
    )
    db.add(flow)
    await db.flush()

    # Auto-create draft v1
    draft = FlowVersion(
        flow_id=flow.id,
        version_number=1,
        status="draft",
    )
    db.add(draft)

    await db.commit()
    await db.refresh(flow)

    logger.info("flow_created", flow_id=str(flow.id), org_id=str(org_id))
    return flow


@router.get("/{flow_id}", response_model=FlowListItem)
async def get_flow(
    flow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get a flow with its current published/draft version info."""
    flow = await _get_flow_or_404(flow_id, org_id, db)
    return flow


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
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
        )

    # Check name uniqueness if name is changing
    if "name" in update_data and update_data["name"] != flow.name:
        dup = await db.execute(
            select(FlowDefinition.id).where(
                FlowDefinition.org_id == org_id,
                FlowDefinition.name == update_data["name"],
                FlowDefinition.id != flow_id,
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Flow named '{update_data['name']}' already exists",
            )

    for key, value in update_data.items():
        setattr(flow, key, value)

    await db.commit()
    await db.refresh(flow)

    logger.info("flow_updated", flow_id=str(flow_id), org_id=str(org_id))
    return flow


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    flow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a flow. Fails if there are active instances."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Check for active instances
    active_count = (
        await db.execute(
            select(func.count()).where(
                FlowInstance.flow_id == flow_id,
                FlowInstance.status.in_(["active", "paused"]),
            )
        )
    ).scalar_one()

    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete flow with {active_count} active/paused instance(s). Cancel them first.",
        )

    await db.delete(flow)
    await db.commit()
    logger.info("flow_deleted", flow_id=str(flow_id), org_id=str(org_id))


@router.post("/{flow_id}/clone", response_model=FlowListItem, status_code=status.HTTP_201_CREATED)
async def clone_flow(
    flow_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate a flow with its published version's nodes and edges."""
    source = await _get_flow_or_404(flow_id, org_id, db)

    # Find a unique name
    clone_name = f"{source.name} (copy)"
    suffix = 1
    while True:
        dup = await db.execute(
            select(FlowDefinition.id).where(
                FlowDefinition.org_id == org_id, FlowDefinition.name == clone_name
            )
        )
        if dup.scalar_one_or_none() is None:
            break
        suffix += 1
        clone_name = f"{source.name} (copy {suffix})"

    new_flow = FlowDefinition(
        org_id=org_id,
        name=clone_name,
        description=source.description,
        trigger_type=source.trigger_type,
        trigger_conditions=source.trigger_conditions,
        max_active_per_lead=source.max_active_per_lead,
        variables=source.variables,
    )
    db.add(new_flow)
    await db.flush()

    # Find source's latest published version (or draft if none published)
    source_version_q = (
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(
            # Prefer published, then by version_number desc
            (FlowVersion.status == "published").desc(),
            FlowVersion.version_number.desc(),
        )
        .limit(1)
    )
    source_version = (await db.execute(source_version_q)).scalar_one_or_none()

    # Create draft v1 for clone
    new_version = FlowVersion(
        flow_id=new_flow.id,
        version_number=1,
        status="draft",
    )
    db.add(new_version)
    await db.flush()

    # Copy nodes and edges if source version exists
    if source_version:
        source_nodes = (
            await db.execute(
                select(FlowNode).where(FlowNode.version_id == source_version.id)
            )
        ).scalars().all()

        node_id_map: dict[uuid.UUID, uuid.UUID] = {}
        for node in source_nodes:
            new_node = FlowNode(
                version_id=new_version.id,
                org_id=org_id,
                node_type=node.node_type,
                name=node.name,
                position_x=node.position_x,
                position_y=node.position_y,
                config=node.config,
            )
            db.add(new_node)
            await db.flush()
            node_id_map[node.id] = new_node.id

        source_edges = (
            await db.execute(
                select(FlowEdge).where(FlowEdge.version_id == source_version.id)
            )
        ).scalars().all()

        for edge in source_edges:
            new_edge = FlowEdge(
                version_id=new_version.id,
                org_id=org_id,
                source_node_id=node_id_map[edge.source_node_id],
                target_node_id=node_id_map[edge.target_node_id],
                condition_label=edge.condition_label,
                sort_order=edge.sort_order,
            )
            db.add(new_edge)

    await db.commit()
    await db.refresh(new_flow)

    logger.info("flow_cloned", source_id=str(flow_id), new_id=str(new_flow.id), org_id=str(org_id))
    return new_flow


# ---------------------------------------------------------------------------
# Version Management
# ---------------------------------------------------------------------------


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
    return result.scalars().all()


@router.get("/{flow_id}/versions/{version_id}", response_model=VersionDetailResponse)
async def get_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get a version with its nodes and edges."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)

    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )

    return VersionDetailResponse(
        id=version.id,
        flow_id=version.flow_id,
        version_number=version.version_number,
        status=version.status,
        is_locked=version.is_locked,
        published_at=version.published_at,
        published_by=version.published_by,
        created_at=version.created_at,
        nodes=nodes_result.scalars().all(),
        edges=edges_result.scalars().all(),
    )


@router.post("/{flow_id}/versions", response_model=VersionListItem, status_code=status.HTTP_201_CREATED)
async def create_version(
    flow_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new draft version, copying from the latest published version."""
    await _get_flow_or_404(flow_id, org_id, db)

    # Check no existing draft
    existing_draft = (
        await db.execute(
            select(FlowVersion.id).where(
                FlowVersion.flow_id == flow_id, FlowVersion.status == "draft"
            )
        )
    ).scalar_one_or_none()

    if existing_draft is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A draft version already exists. Publish or delete it first.",
        )

    # Get latest version number
    max_ver = (
        await db.execute(
            select(func.max(FlowVersion.version_number)).where(
                FlowVersion.flow_id == flow_id
            )
        )
    ).scalar_one() or 0

    new_version = FlowVersion(
        flow_id=flow_id,
        version_number=max_ver + 1,
        status="draft",
    )
    db.add(new_version)
    await db.flush()

    # Copy nodes/edges from latest published version
    published = (
        await db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "published")
            .order_by(FlowVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if published:
        source_nodes = (
            await db.execute(select(FlowNode).where(FlowNode.version_id == published.id))
        ).scalars().all()

        node_id_map: dict[uuid.UUID, uuid.UUID] = {}
        for node in source_nodes:
            new_node = FlowNode(
                version_id=new_version.id,
                org_id=org_id,
                node_type=node.node_type,
                name=node.name,
                position_x=node.position_x,
                position_y=node.position_y,
                config=node.config,
            )
            db.add(new_node)
            await db.flush()
            node_id_map[node.id] = new_node.id

        source_edges = (
            await db.execute(select(FlowEdge).where(FlowEdge.version_id == published.id))
        ).scalars().all()

        for edge in source_edges:
            new_edge = FlowEdge(
                version_id=new_version.id,
                org_id=org_id,
                source_node_id=node_id_map[edge.source_node_id],
                target_node_id=node_id_map[edge.target_node_id],
                condition_label=edge.condition_label,
                sort_order=edge.sort_order,
            )
            db.add(new_edge)

    await db.commit()
    await db.refresh(new_version)

    logger.info(
        "flow_version_created",
        flow_id=str(flow_id),
        version_id=str(new_version.id),
        version_number=new_version.version_number,
    )
    return new_version


@router.put("/{flow_id}/versions/{version_id}", response_model=VersionDetailResponse)
async def save_graph(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: GraphSaveRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Atomic graph save — replaces all nodes and edges in a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    # Delete existing nodes and edges (cascade will handle edges via FK)
    await db.execute(delete(FlowEdge).where(FlowEdge.version_id == version_id))
    await db.execute(delete(FlowNode).where(FlowNode.version_id == version_id))
    await db.flush()

    # Insert new nodes
    node_id_map: dict[str, uuid.UUID] = {}
    for node_data in body.nodes:
        node = FlowNode(
            version_id=version_id,
            org_id=org_id,
            node_type=node_data.node_type,
            name=node_data.name,
            position_x=node_data.position_x,
            position_y=node_data.position_y,
            config=node_data.config,
        )
        # Use client-provided ID if present, for edge references
        if node_data.id:
            node.id = node_data.id
        db.add(node)
        await db.flush()
        node_id_map[str(node_data.id) if node_data.id else str(node.id)] = node.id

    # Insert new edges
    for edge_data in body.edges:
        edge = FlowEdge(
            version_id=version_id,
            org_id=org_id,
            source_node_id=edge_data.source_node_id,
            target_node_id=edge_data.target_node_id,
            condition_label=edge_data.condition_label,
            sort_order=edge_data.sort_order if edge_data.sort_order else 0,
        )
        db.add(edge)

    await db.commit()

    # Return the saved version with nodes and edges
    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )

    return VersionDetailResponse(
        id=version.id,
        flow_id=version.flow_id,
        version_number=version.version_number,
        status=version.status,
        is_locked=version.is_locked,
        published_at=version.published_at,
        published_by=version.published_by,
        created_at=version.created_at,
        nodes=nodes_result.scalars().all(),
        edges=edges_result.scalars().all(),
    )


@router.post("/{flow_id}/versions/{version_id}/publish", response_model=VersionListItem)
async def publish_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Validate and publish a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    # Load nodes and edges for validation
    nodes = (
        await db.execute(select(FlowNode).where(FlowNode.version_id == version_id))
    ).scalars().all()
    edges = (
        await db.execute(select(FlowEdge).where(FlowEdge.version_id == version_id))
    ).scalars().all()

    validation = validate_flow(nodes, edges)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Flow validation failed",
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )

    # Archive current published version
    await db.execute(
        select(FlowVersion)
        .where(
            FlowVersion.flow_id == flow_id,
            FlowVersion.status == "published",
        )
    )
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(FlowVersion)
        .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "published")
        .values(status="archived")
    )

    # Publish this version
    version.status = "published"
    version.is_locked = True
    version.published_at = datetime.now(timezone.utc)
    version.published_by = user.id

    await db.commit()
    await db.refresh(version)

    logger.info(
        "flow_version_published",
        flow_id=str(flow_id),
        version_id=str(version_id),
        version_number=version.version_number,
    )
    return version


@router.post("/{flow_id}/versions/{version_id}/validate", response_model=ValidationResult)
async def validate_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Run validation on a version without publishing."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_version_or_404(version_id, flow_id, db)

    nodes = (
        await db.execute(select(FlowNode).where(FlowNode.version_id == version_id))
    ).scalars().all()
    edges = (
        await db.execute(select(FlowEdge).where(FlowEdge.version_id == version_id))
    ).scalars().all()

    return validate_flow(nodes, edges)


# ---------------------------------------------------------------------------
# Node/Edge Operations (within draft version)
# ---------------------------------------------------------------------------


@router.post(
    "/{flow_id}/versions/{version_id}/nodes",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: NodeCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Add a node to a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

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
    return node


@router.put("/{flow_id}/versions/{version_id}/nodes/{node_id}", response_model=NodeResponse)
async def update_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    node_id: uuid.UUID,
    body: NodeCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update a node in a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    result = await db.execute(
        select(FlowNode).where(
            FlowNode.id == node_id, FlowNode.version_id == version_id
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    node.node_type = body.node_type
    node.name = body.name
    node.position_x = body.position_x
    node.position_y = body.position_y
    node.config = body.config

    await db.commit()
    await db.refresh(node)
    return node


@router.delete(
    "/{flow_id}/versions/{version_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_node(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    node_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a node and its connected edges from a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    result = await db.execute(
        select(FlowNode).where(
            FlowNode.id == node_id, FlowNode.version_id == version_id
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    # Delete connected edges first
    await db.execute(
        delete(FlowEdge).where(
            FlowEdge.version_id == version_id,
            (FlowEdge.source_node_id == node_id) | (FlowEdge.target_node_id == node_id),
        )
    )
    await db.delete(node)
    await db.commit()


@router.post(
    "/{flow_id}/versions/{version_id}/edges",
    response_model=EdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_edge(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: EdgeCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Add an edge to a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    # Verify both nodes exist in this version
    for nid in [body.source_node_id, body.target_node_id]:
        exists = (
            await db.execute(
                select(FlowNode.id).where(
                    FlowNode.id == nid, FlowNode.version_id == version_id
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Node {nid} not found in this version",
            )

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
    return edge


@router.delete(
    "/{flow_id}/versions/{version_id}/edges/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_edge(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    edge_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete an edge from a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    result = await db.execute(
        select(FlowEdge).where(
            FlowEdge.id == edge_id, FlowEdge.version_id == version_id
        )
    )
    edge = result.scalar_one_or_none()
    if edge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")

    await db.delete(edge)
    await db.commit()


@router.put("/{flow_id}/versions/{version_id}/layout", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_update_layout(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: BulkLayoutRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Bulk update node positions in a draft version."""
    await _get_flow_or_404(flow_id, org_id, db)
    version = await _get_version_or_404(version_id, flow_id, db)
    _require_draft(version)

    for pos in body.positions:
        result = await db.execute(
            select(FlowNode).where(
                FlowNode.id == pos.node_id, FlowNode.version_id == version_id
            )
        )
        node = result.scalar_one_or_none()
        if node is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node {pos.node_id} not found in this version",
            )
        node.position_x = pos.position_x
        node.position_y = pos.position_y

    await db.commit()


# ---------------------------------------------------------------------------
# Instance Management
# ---------------------------------------------------------------------------


@router.get("/{flow_id}/instances", response_model=PaginatedInstances)
async def list_instances(
    flow_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List instances for a flow."""
    await _get_flow_or_404(flow_id, org_id, db)

    base = select(FlowInstance).where(
        FlowInstance.flow_id == flow_id, FlowInstance.org_id == org_id
    )

    if status_filter:
        base = base.where(FlowInstance.status == status_filter)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.order_by(FlowInstance.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedInstances(items=items, total=total, page=page, page_size=page_size)


@router.get("/instances/{instance_id}", response_model=InstanceDetailResponse)
async def get_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get an instance with its touchpoints and transitions."""
    instance = await _get_instance_or_404(instance_id, org_id, db)

    touchpoints_result = await db.execute(
        select(FlowTouchpoint)
        .where(FlowTouchpoint.instance_id == instance_id)
        .order_by(FlowTouchpoint.scheduled_at.asc())
    )
    transitions_result = await db.execute(
        select(FlowTransition)
        .where(FlowTransition.instance_id == instance_id)
        .order_by(FlowTransition.transitioned_at.asc())
    )

    return InstanceDetailResponse(
        id=instance.id,
        org_id=instance.org_id,
        flow_id=instance.flow_id,
        version_id=instance.version_id,
        lead_id=instance.lead_id,
        trigger_call_id=instance.trigger_call_id,
        status=instance.status,
        current_node_id=instance.current_node_id,
        context_data=instance.context_data,
        error_message=instance.error_message,
        is_test=instance.is_test,
        started_at=instance.started_at,
        completed_at=instance.completed_at,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        touchpoints=touchpoints_result.scalars().all(),
        transitions=transitions_result.scalars().all(),
    )


@router.post("/{flow_id}/enroll", response_model=list[InstanceListItem], status_code=status.HTTP_201_CREATED)
async def enroll_leads(
    flow_id: uuid.UUID,
    body: FlowEnrollRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Enroll one or more leads into a flow."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    if not flow.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Flow is not active"
        )

    # Get published version
    published = (
        await db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "published")
            .order_by(FlowVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if published is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flow has no published version. Publish a version before enrolling leads.",
        )

    # Find the entry node (first node to start from)
    entry_node = (
        await db.execute(
            select(FlowNode)
            .where(FlowNode.version_id == published.id)
            .order_by(FlowNode.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    instances: list[FlowInstance] = []
    skipped: list[str] = []

    for lead_id in body.lead_ids:
        # Check max active instances per lead
        active_count = (
            await db.execute(
                select(func.count()).where(
                    FlowInstance.flow_id == flow_id,
                    FlowInstance.lead_id == lead_id,
                    FlowInstance.status.in_(["active", "paused"]),
                )
            )
        ).scalar_one()

        if active_count >= flow.max_active_per_lead:
            skipped.append(str(lead_id))
            continue

        instance = FlowInstance(
            org_id=org_id,
            flow_id=flow_id,
            version_id=published.id,
            lead_id=lead_id,
            status="active",
            current_node_id=entry_node.id if entry_node else None,
            context_data=body.context_data if body.context_data else {},
            trigger_call_id=body.trigger_call_id,
        )
        db.add(instance)
        instances.append(instance)

    await db.commit()
    for inst in instances:
        await db.refresh(inst)

    if skipped:
        logger.info(
            "flow_enroll_skipped",
            flow_id=str(flow_id),
            skipped_leads=skipped,
            reason="max_active_per_lead",
        )

    logger.info(
        "flow_leads_enrolled",
        flow_id=str(flow_id),
        enrolled=len(instances),
        skipped=len(skipped),
    )
    return instances


@router.post("/instances/{instance_id}/cancel", response_model=InstanceListItem)
async def cancel_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a flow instance."""
    instance = await _get_instance_or_404(instance_id, org_id, db)

    if instance.status not in ("active", "paused"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel instance with status '{instance.status}'",
        )

    instance.status = "cancelled"
    instance.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(instance)

    logger.info("flow_instance_cancelled", instance_id=str(instance_id))
    return instance


@router.post("/instances/{instance_id}/pause", response_model=InstanceListItem)
async def pause_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Pause a flow instance."""
    instance = await _get_instance_or_404(instance_id, org_id, db)

    if instance.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot pause instance with status '{instance.status}'. Only active instances can be paused.",
        )

    instance.status = "paused"
    await db.commit()
    await db.refresh(instance)

    logger.info("flow_instance_paused", instance_id=str(instance_id))
    return instance


@router.post("/instances/{instance_id}/resume", response_model=InstanceListItem)
async def resume_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused flow instance."""
    instance = await _get_instance_or_404(instance_id, org_id, db)

    if instance.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resume instance with status '{instance.status}'. Only paused instances can be resumed.",
        )

    instance.status = "active"
    await db.commit()
    await db.refresh(instance)

    logger.info("flow_instance_resumed", instance_id=str(instance_id))
    return instance


@router.post("/instances/{instance_id}/reenroll", response_model=InstanceListItem, status_code=status.HTTP_201_CREATED)
async def reenroll_instance(
    instance_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel current instance and re-enroll the lead on the latest published version."""
    instance = await _get_instance_or_404(instance_id, org_id, db)

    # Cancel current instance if still active
    if instance.status in ("active", "paused"):
        instance.status = "cancelled"
        instance.completed_at = datetime.now(timezone.utc)

    # Get latest published version
    published = (
        await db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == instance.flow_id, FlowVersion.status == "published")
            .order_by(FlowVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if published is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flow has no published version to re-enroll on.",
        )

    entry_node = (
        await db.execute(
            select(FlowNode)
            .where(FlowNode.version_id == published.id)
            .order_by(FlowNode.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    new_instance = FlowInstance(
        org_id=org_id,
        flow_id=instance.flow_id,
        version_id=published.id,
        lead_id=instance.lead_id,
        status="active",
        current_node_id=entry_node.id if entry_node else None,
        context_data=instance.context_data,
    )
    db.add(new_instance)
    await db.commit()
    await db.refresh(new_instance)

    logger.info(
        "flow_instance_reenrolled",
        old_instance_id=str(instance_id),
        new_instance_id=str(new_instance.id),
    )
    return new_instance


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@router.post("/{flow_id}/versions/{version_id}/simulate", response_model=SimulateResponse)
async def simulate_version(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: SimulateRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run simulation of a flow version."""
    await _get_flow_or_404(flow_id, org_id, db)
    await _get_version_or_404(version_id, flow_id, db)

    nodes = (
        await db.execute(select(FlowNode).where(FlowNode.version_id == version_id))
    ).scalars().all()
    edges = (
        await db.execute(select(FlowEdge).where(FlowEdge.version_id == version_id))
    ).scalars().all()

    result = simulate_flow(nodes, edges, body)
    return result


@router.post("/{flow_id}/live-test", response_model=InstanceListItem, status_code=status.HTTP_201_CREATED)
async def start_live_test(
    flow_id: uuid.UUID,
    body: LiveTestRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Start a live test of a flow — creates a test instance."""
    flow = await _get_flow_or_404(flow_id, org_id, db)

    # Use draft version for live testing (so you can test before publishing)
    draft = (
        await db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "draft")
            .limit(1)
        )
    ).scalar_one_or_none()

    # Fall back to published
    version = draft
    if version is None:
        version = (
            await db.execute(
                select(FlowVersion)
                .where(FlowVersion.flow_id == flow_id, FlowVersion.status == "published")
                .order_by(FlowVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flow has no draft or published version to test.",
        )

    entry_node = (
        await db.execute(
            select(FlowNode)
            .where(FlowNode.version_id == version.id)
            .order_by(FlowNode.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    instance = FlowInstance(
        org_id=org_id,
        flow_id=flow_id,
        version_id=version.id,
        lead_id=body.lead_id,
        status="active",
        current_node_id=entry_node.id if entry_node else None,
        context_data={"phone_number": body.phone_number} if body.phone_number else {},
        is_test=True,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    logger.info(
        "flow_live_test_started",
        flow_id=str(flow_id),
        instance_id=str(instance.id),
        version_id=str(version.id),
    )
    return instance


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


@router.get("/{flow_id}/versions/{version_id}/export")
async def export_flow(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Export a flow version as portable JSON."""
    try:
        data = await export_flow_version(db, flow_id, version_id, org_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return data


class FlowImportRequest(BaseModel):
    name: str
    description: str = ""
    trigger_type: str = "manual"
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_flow_endpoint(
    body: FlowImportRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Import a flow from JSON (creates new flow as draft)."""
    try:
        result = await import_flow(db, org_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return result


@router.post("/{flow_id}/import-version", status_code=status.HTTP_201_CREATED)
async def import_flow_version_endpoint(
    flow_id: uuid.UUID,
    body: FlowImportRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Import JSON as a new version of an existing flow."""
    try:
        result = await import_flow(db, org_id, body.model_dump(), target_flow_id=flow_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return result
