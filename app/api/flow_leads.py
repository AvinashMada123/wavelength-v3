"""Lead-flow integration API — flow history, canvas leads panel, node counts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-leads"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FlowEnrollment(BaseModel):
    instance_id: str
    flow_id: str
    flow_name: str
    version_number: int
    status: str
    current_node_id: str | None
    enrolled_at: datetime
    completed_at: datetime | None
    error_message: str | None


class LeadFlowHistoryResponse(BaseModel):
    lead_id: str
    enrollments: list[FlowEnrollment]


class TransitionStep(BaseModel):
    from_node_id: str | None
    to_node_id: str
    node_type: str
    node_label: str
    outcome_data: dict[str, Any] | None
    transitioned_at: datetime
    touchpoint_status: str | None
    touchpoint_error: str | None


class JourneyResponse(BaseModel):
    instance_id: str
    transitions: list[TransitionStep]


class CanvasLead(BaseModel):
    instance_id: str
    lead_id: str
    lead_name: str | None
    lead_phone: str | None
    status: str
    current_node_id: str | None
    current_node_label: str | None
    enrolled_at: datetime


class CanvasLeadsResponse(BaseModel):
    flow_id: str
    leads: list[CanvasLead]
    total: int
    page: int
    page_size: int


class NodeCountsResponse(BaseModel):
    flow_id: str
    counts: dict[str, int]  # node_id -> active lead count


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

PAGE_SIZE = 50


@router.get("/leads/{lead_id}/history", response_model=LeadFlowHistoryResponse)
async def get_lead_flow_history(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get chronological list of all flow enrollments for a lead."""
    query = text("""
        SELECT
            fi.id,
            fi.flow_id,
            fd.name AS flow_name,
            fv.version_number,
            fi.status,
            fi.current_node_id,
            fi.enrolled_at,
            fi.completed_at,
            fi.error_message
        FROM flow_instances fi
        JOIN flow_versions fv ON fi.version_id = fv.id
        JOIN flow_definitions fd ON fv.flow_id = fd.id
        WHERE fi.lead_id = :lead_id
          AND fi.org_id = :org_id
        ORDER BY fi.enrolled_at DESC
    """)
    result = await db.execute(
        query, {"lead_id": str(lead_id), "org_id": str(org.id)}
    )
    rows = result.all()

    enrollments = [
        FlowEnrollment(
            instance_id=str(r.id),
            flow_id=str(r.flow_id),
            flow_name=r.flow_name,
            version_number=r.version_number,
            status=r.status,
            current_node_id=str(r.current_node_id) if r.current_node_id else None,
            enrolled_at=r.enrolled_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
        )
        for r in rows
    ]

    return LeadFlowHistoryResponse(
        lead_id=str(lead_id),
        enrollments=enrollments,
    )


@router.get("/instances/{instance_id}/journey", response_model=JourneyResponse)
async def get_instance_journey(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get node-by-node journey with timestamps and outcomes for an instance."""
    query = text("""
        SELECT
            ft.from_node_id,
            ft.to_node_id,
            fn.node_type,
            fn.label AS node_label,
            ft.outcome_data,
            ft.transitioned_at,
            ftp.status AS touchpoint_status,
            ftp.error_message AS touchpoint_error
        FROM flow_transitions ft
        JOIN flow_nodes fn ON ft.to_node_id = fn.id
        LEFT JOIN flow_touchpoints ftp
            ON ftp.instance_id = ft.instance_id
           AND ftp.node_id = ft.to_node_id
        JOIN flow_instances fi ON ft.instance_id = fi.id
        WHERE ft.instance_id = :instance_id
          AND fi.org_id = :org_id
        ORDER BY ft.transitioned_at ASC
    """)
    result = await db.execute(
        query, {"instance_id": str(instance_id), "org_id": str(org.id)}
    )
    rows = result.all()

    transitions = [
        TransitionStep(
            from_node_id=str(r.from_node_id) if r.from_node_id else None,
            to_node_id=str(r.to_node_id),
            node_type=r.node_type,
            node_label=r.node_label,
            outcome_data=r.outcome_data,
            transitioned_at=r.transitioned_at,
            touchpoint_status=r.touchpoint_status,
            touchpoint_error=r.touchpoint_error,
        )
        for r in rows
    ]

    return JourneyResponse(
        instance_id=str(instance_id),
        transitions=transitions,
    )


@router.get("/{flow_id}/leads", response_model=CanvasLeadsResponse)
async def get_canvas_leads(
    flow_id: uuid.UUID,
    status: str | None = Query(None, description="Filter by instance status"),
    node_id: uuid.UUID | None = Query(None, description="Filter by current node"),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get leads currently in a flow for the canvas leads panel."""
    base_where = """
        fi.flow_id = :flow_id
        AND fi.org_id = :org_id
    """
    params: dict[str, Any] = {
        "flow_id": str(flow_id),
        "org_id": str(org.id),
    }

    if status:
        base_where += " AND fi.status = :status"
        params["status"] = status
    if node_id:
        base_where += " AND fi.current_node_id = :node_id"
        params["node_id"] = str(node_id)

    # Count
    count_query = text(f"""
        SELECT COUNT(*) FROM flow_instances fi WHERE {base_where}
    """)
    count_result = await db.execute(count_query, params)
    total = count_result.scalar() or 0

    # Paginated leads
    offset = (page - 1) * PAGE_SIZE
    params["limit"] = PAGE_SIZE
    params["offset"] = offset

    data_query = text(f"""
        SELECT
            fi.id AS instance_id,
            fi.lead_id,
            l.contact_name AS lead_name,
            l.phone_number AS lead_phone,
            fi.status,
            fi.current_node_id,
            fn.label AS current_node_label,
            fi.enrolled_at
        FROM flow_instances fi
        JOIN leads l ON fi.lead_id = l.id
        LEFT JOIN flow_nodes fn ON fi.current_node_id = fn.id
        WHERE {base_where}
        ORDER BY fi.enrolled_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(data_query, params)
    rows = result.all()

    leads = [
        CanvasLead(
            instance_id=str(r.instance_id),
            lead_id=str(r.lead_id),
            lead_name=r.lead_name,
            lead_phone=r.lead_phone,
            status=r.status,
            current_node_id=str(r.current_node_id) if r.current_node_id else None,
            current_node_label=r.current_node_label,
            enrolled_at=r.enrolled_at,
        )
        for r in rows
    ]

    return CanvasLeadsResponse(
        flow_id=str(flow_id),
        leads=leads,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
    )


@router.get("/{flow_id}/node-counts", response_model=NodeCountsResponse)
async def get_node_lead_counts(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get per-node active lead counts for canvas badges."""
    query = text("""
        SELECT
            fi.current_node_id,
            COUNT(*) AS count
        FROM flow_instances fi
        WHERE fi.flow_id = :flow_id
          AND fi.org_id = :org_id
          AND fi.status = 'active'
          AND fi.current_node_id IS NOT NULL
        GROUP BY fi.current_node_id
    """)
    result = await db.execute(
        query, {"flow_id": str(flow_id), "org_id": str(org.id)}
    )
    rows = result.all()

    counts = {str(r.current_node_id): r.count for r in rows}

    return NodeCountsResponse(
        flow_id=str(flow_id),
        counts=counts,
    )
