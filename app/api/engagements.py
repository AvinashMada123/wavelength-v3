"""Lead engagement tracking API.

Endpoints for n8n to create engagement records and update
touchpoint message data after each WATI/GHL send.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.engagement_service import (
    create_engagement,
    get_engagement,
    update_report_link,
    update_touchpoint,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/engagements", tags=["engagements"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateEngagementRequest(BaseModel):
    call_log_id: uuid.UUID
    contact_phone: str
    contact_email: str | None = None
    extraction_data: dict = Field(default_factory=dict)
    ghl_contact_id: str | None = None


class CreateEngagementResponse(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID
    status: str = "created"


class UpdateTouchpointRequest(BaseModel):
    touchpoint_key: str
    message_id: str
    conversation_id: str | None = None
    template: str | None = None
    subject: str | None = None
    status: str = "sent"


class UpdateTouchpointResponse(BaseModel):
    call_log_id: uuid.UUID
    touchpoint_key: str
    status: str = "updated"


class UpdateReportLinkRequest(BaseModel):
    report_link: str

    @field_validator("report_link")
    @classmethod
    def report_link_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("report_link cannot be empty")
        return v


class EngagementResponse(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID
    contact_phone: str
    contact_email: str | None
    extraction_data: dict
    touchpoints: dict
    report_link: str | None
    ghl_contact_id: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def api_create_engagement(
    body: CreateEngagementRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateEngagementResponse:
    """Create engagement record after Gemini extraction. Called by n8n."""
    from app.models.call_log import CallLog
    from sqlalchemy import select

    result = await db.execute(select(CallLog).where(CallLog.id == body.call_log_id))
    call_log = result.scalar_one_or_none()
    if not call_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call log {body.call_log_id} not found",
        )

    try:
        engagement = await create_engagement(
            db=db,
            org_id=call_log.org_id,
            call_log_id=body.call_log_id,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
            extraction_data=body.extraction_data,
            ghl_contact_id=body.ghl_contact_id,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Engagement already exists for call_log_id {body.call_log_id}",
            )
        raise

    return CreateEngagementResponse(id=engagement.id, call_log_id=engagement.call_log_id)


@router.patch("/{call_log_id}/touchpoint")
async def api_update_touchpoint(
    call_log_id: uuid.UUID,
    body: UpdateTouchpointRequest,
    db: AsyncSession = Depends(get_db),
) -> UpdateTouchpointResponse:
    """Update touchpoint message data after a send. Called by n8n."""
    message_data = {
        "message_id": body.message_id,
        "status": body.status,
    }
    if body.conversation_id:
        message_data["conversation_id"] = body.conversation_id
    if body.template:
        message_data["template"] = body.template
    if body.subject:
        message_data["subject"] = body.subject

    result = await update_touchpoint(
        db=db,
        call_log_id=call_log_id,
        touchpoint_key=body.touchpoint_key,
        message_data=message_data,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id} or invalid touchpoint key",
        )

    return UpdateTouchpointResponse(call_log_id=call_log_id, touchpoint_key=body.touchpoint_key)


@router.patch("/{call_log_id}/report-link")
async def api_update_report_link(
    call_log_id: uuid.UUID,
    body: UpdateReportLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set report PDF link after GCS upload. Called by n8n."""
    result = await update_report_link(db=db, call_log_id=call_log_id, report_link=body.report_link)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id}",
        )
    return {"call_log_id": str(call_log_id), "status": "updated"}


@router.get("/{call_log_id}")
async def api_get_engagement(
    call_log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EngagementResponse:
    """Get full engagement record."""
    engagement = await get_engagement(db=db, call_log_id=call_log_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id}",
        )
    return EngagementResponse(
        id=engagement.id,
        call_log_id=engagement.call_log_id,
        contact_phone=engagement.contact_phone,
        contact_email=engagement.contact_email,
        extraction_data=engagement.extraction_data,
        touchpoints=engagement.touchpoints,
        report_link=engagement.report_link,
        ghl_contact_id=engagement.ghl_contact_id,
        created_at=engagement.created_at.isoformat() if engagement.created_at else "",
        updated_at=engagement.updated_at.isoformat() if engagement.updated_at else "",
    )
