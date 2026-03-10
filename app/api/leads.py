"""CRUD API for leads management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.lead import Lead
from app.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class LeadCreate(BaseModel):
    phone_number: str
    contact_name: str
    email: str | None = None
    company: str | None = None
    location: str | None = None
    tags: list[Any] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    ghl_contact_id: str | None = None
    source: str = "manual"


class LeadUpdate(BaseModel):
    phone_number: str | None = None
    contact_name: str | None = None
    email: str | None = None
    company: str | None = None
    location: str | None = None
    tags: list[Any] | None = None
    custom_fields: dict[str, Any] | None = None
    status: str | None = None
    qualification_level: str | None = None
    qualification_confidence: float | None = None
    ghl_contact_id: str | None = None
    source: str | None = None
    bot_notes: str | None = None


class LeadResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    phone_number: str
    contact_name: str
    email: str | None
    company: str | None
    location: str | None
    tags: list[Any]
    custom_fields: dict[str, Any]
    status: str
    qualification_level: str | None
    qualification_confidence: float | None
    call_count: int
    last_call_date: datetime | None
    source: str
    ghl_contact_id: str | None
    bot_notes: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedLeads(BaseModel):
    items: list[LeadResponse]
    total: int
    page: int
    page_size: int


class BulkImportRequest(BaseModel):
    leads: list[LeadCreate]


class BulkImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedLeads)
async def list_leads(
    status: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List leads for the current organisation with optional filtering."""
    base = select(Lead).where(Lead.org_id == org_id)

    if status:
        base = base.where(Lead.status == status)

    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                Lead.contact_name.ilike(pattern),
                Lead.phone_number.ilike(pattern),
                Lead.email.ilike(pattern),
            )
        )

    # Total count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginated rows
    rows_q = base.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedLeads(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=LeadResponse, status_code=201)
async def create_lead(
    body: LeadCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a single lead. Returns 409 if phone_number already exists in the org."""
    # Duplicate check
    dup = await db.execute(
        select(Lead.id).where(Lead.org_id == org_id, Lead.phone_number == body.phone_number)
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A lead with phone number '{body.phone_number}' already exists in this organisation",
        )

    lead = Lead(
        org_id=org_id,
        phone_number=body.phone_number,
        contact_name=body.contact_name,
        email=body.email,
        company=body.company,
        location=body.location,
        tags=body.tags,
        custom_fields=body.custom_fields,
        ghl_contact_id=body.ghl_contact_id,
        source=body.source,
        created_by=user.id,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    logger.info("lead_created", lead_id=str(lead.id), org_id=str(org_id))
    return lead


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get a single lead by ID. Must belong to the current org."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Partial update of a lead. Must belong to the current org."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)

    await db.commit()
    await db.refresh(lead)

    logger.info("lead_updated", lead_id=str(lead_id), fields=list(update_data.keys()))
    return lead


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a lead. Must belong to the current org."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    await db.delete(lead)
    await db.commit()

    logger.info("lead_deleted", lead_id=str(lead_id), org_id=str(org_id))


@router.post("/import", response_model=BulkImportResponse)
async def bulk_import_leads(
    body: BulkImportRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Bulk import leads from a JSON array. Skips duplicates by phone within org."""
    # Pre-fetch existing phone numbers for this org to avoid N+1 queries
    existing_q = await db.execute(
        select(Lead.phone_number).where(Lead.org_id == org_id)
    )
    existing_phones: set[str] = {row[0] for row in existing_q.all()}

    imported = 0
    skipped = 0
    errors: list[str] = []
    seen_in_batch: set[str] = set()

    for idx, item in enumerate(body.leads):
        try:
            if item.phone_number in existing_phones or item.phone_number in seen_in_batch:
                skipped += 1
                continue

            lead = Lead(
                org_id=org_id,
                phone_number=item.phone_number,
                contact_name=item.contact_name,
                email=item.email,
                company=item.company,
                location=item.location,
                tags=item.tags,
                custom_fields=item.custom_fields,
                ghl_contact_id=item.ghl_contact_id,
                source=item.source,
                created_by=user.id,
            )
            db.add(lead)
            seen_in_batch.add(item.phone_number)
            imported += 1
        except Exception as exc:
            errors.append(f"Row {idx}: {exc}")

    await db.commit()

    logger.info(
        "leads_bulk_imported",
        org_id=str(org_id),
        imported=imported,
        skipped=skipped,
        errors=len(errors),
    )
    return BulkImportResponse(imported=imported, skipped=skipped, errors=errors)
