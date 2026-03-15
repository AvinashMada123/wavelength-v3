"""CRUD API for campaigns management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.bot_config import BotConfig
from app.models.campaign import Campaign, CampaignLead
from app.models.call_queue import QueuedCall
from app.models.lead import Lead
from app.models.user import User
from app.utils import normalize_phone_india

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CampaignCreate(BaseModel):
    name: str
    bot_config_id: uuid.UUID
    lead_ids: list[uuid.UUID]
    concurrency_limit: int = 3


class CampaignResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bot_config_id: uuid.UUID
    name: str
    status: str
    total_leads: int
    completed_leads: int
    failed_leads: int
    concurrency_limit: int
    created_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class CampaignDetailResponse(CampaignResponse):
    lead_status_breakdown: dict[str, int] = Field(default_factory=dict)


class PaginatedCampaigns(BaseModel):
    items: list[CampaignResponse]
    total: int
    page: int
    page_size: int


class CampaignLeadResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    lead_id: uuid.UUID
    status: str
    call_log_id: uuid.UUID | None
    position: int
    retry_count: int
    created_at: datetime
    processed_at: datetime | None
    # Joined lead fields
    phone_number: str | None = None
    contact_name: str | None = None
    email: str | None = None
    company: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedCampaignLeads(BaseModel):
    items: list[CampaignLeadResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_campaign_or_404(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.org_id == org_id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _lead_status_breakdown(campaign_id: uuid.UUID, db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(CampaignLead.status, func.count())
        .where(CampaignLead.campaign_id == campaign_id)
        .group_by(CampaignLead.status)
    )
    return {status: count for status, count in rows.all()}


async def _enqueue_campaign_leads(
    db: AsyncSession,
    campaign: Campaign,
    limit: int | None = None,
) -> int:
    """Enqueue the next batch of queued CampaignLeads into call_queue.

    Args:
        db: Active database session (caller must commit).
        campaign: The campaign to enqueue leads for.
        limit: Max leads to enqueue. Defaults to campaign.concurrency_limit
               minus currently-processing leads.

    Returns:
        Number of leads enqueued.
    """
    if limit is None:
        # Count how many campaign leads are already processing
        processing_count_result = await db.execute(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.status == "processing",
            )
        )
        currently_processing = processing_count_result.scalar_one()
        limit = max(0, campaign.concurrency_limit - currently_processing)

    if limit <= 0:
        return 0

    # Fetch next queued leads ordered by position
    result = await db.execute(
        select(CampaignLead)
        .where(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.status == "queued",
        )
        .order_by(CampaignLead.position.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    leads_to_enqueue = result.scalars().all()

    if not leads_to_enqueue:
        return 0

    # Batch-fetch lead details (phone, name)
    lead_ids = [cl.lead_id for cl in leads_to_enqueue]
    lead_result = await db.execute(
        select(Lead).where(Lead.id.in_(lead_ids))
    )
    lead_map = {lead.id: lead for lead in lead_result.scalars().all()}

    enqueued = 0
    for cl in leads_to_enqueue:
        lead = lead_map.get(cl.lead_id)
        if not lead:
            # Lead was deleted -- mark as failed
            cl.status = "failed"
            cl.processed_at = datetime.now(timezone.utc)
            campaign.failed_leads += 1
            logger.warning(
                "campaign_lead_missing",
                campaign_id=str(campaign.id),
                lead_id=str(cl.lead_id),
            )
            continue

        normalized_phone = normalize_phone_india(lead.phone_number)
        queued_call = QueuedCall(
            org_id=campaign.org_id,
            bot_id=campaign.bot_config_id,
            contact_name=lead.contact_name,
            contact_phone=normalized_phone,
            source="campaign",
            status="queued",
            priority=0,
            campaign_id=campaign.id,
            campaign_lead_id=cl.id,
            extra_vars={
                "campaign_id": str(campaign.id),
                "campaign_lead_id": str(cl.id),
            },
        )
        db.add(queued_call)

        cl.status = "processing"
        enqueued += 1

    return enqueued


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedCampaigns)
async def list_campaigns(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List campaigns for the current organisation."""
    base = select(Campaign).where(Campaign.org_id == org_id)

    if status:
        base = base.where(Campaign.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = base.order_by(Campaign.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedCampaigns(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=CampaignDetailResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a campaign and its campaign_lead entries."""
    # Validate bot_config belongs to the org
    bc_result = await db.execute(
        select(BotConfig.id).where(BotConfig.id == body.bot_config_id, BotConfig.org_id == org_id)
    )
    if bc_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bot config not found or does not belong to this organisation")

    # Validate that all lead_ids belong to the org
    if body.lead_ids:
        valid_leads_q = await db.execute(
            select(Lead.id).where(Lead.id.in_(body.lead_ids), Lead.org_id == org_id)
        )
        valid_lead_ids = {row[0] for row in valid_leads_q.all()}
        invalid = set(body.lead_ids) - valid_lead_ids
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"The following lead IDs are invalid or do not belong to this organisation: {[str(lid) for lid in invalid]}",
            )
    else:
        valid_lead_ids = set()

    campaign = Campaign(
        org_id=org_id,
        bot_config_id=body.bot_config_id,
        name=body.name,
        concurrency_limit=body.concurrency_limit,
        total_leads=len(valid_lead_ids),
        created_by=user.id,
    )
    db.add(campaign)
    await db.flush()  # get campaign.id

    # Create campaign_lead entries with position ordering
    for position, lead_id in enumerate(body.lead_ids):
        if lead_id in valid_lead_ids:
            cl = CampaignLead(
                campaign_id=campaign.id,
                lead_id=lead_id,
                position=position,
            )
            db.add(cl)

    await db.commit()
    await db.refresh(campaign)

    breakdown = await _lead_status_breakdown(campaign.id, db)

    logger.info("campaign_created", campaign_id=str(campaign.id), org_id=str(org_id), leads=len(valid_lead_ids))
    return CampaignDetailResponse(
        **{c.key: getattr(campaign, c.key) for c in Campaign.__table__.columns},
        lead_status_breakdown=breakdown,
    )


@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get campaign details including lead status breakdown."""
    campaign = await _get_campaign_or_404(campaign_id, org_id, db)
    breakdown = await _lead_status_breakdown(campaign.id, db)

    return CampaignDetailResponse(
        **{c.key: getattr(campaign, c.key) for c in Campaign.__table__.columns},
        lead_status_breakdown=breakdown,
    )


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Start a campaign. Only allowed from 'draft' or 'paused' status.

    Sets status to 'running' and enqueues the first batch of calls
    (up to concurrency_limit) into the call_queue for the background
    queue processor to pick up.
    """
    campaign = await _get_campaign_or_404(campaign_id, org_id, db)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start campaign with status '{campaign.status}'. Must be 'draft' or 'paused'.",
        )

    campaign.status = "running"
    campaign.started_at = campaign.started_at or datetime.now(timezone.utc)

    # Enqueue first batch of leads into call_queue
    enqueued = await _enqueue_campaign_leads(db, campaign)

    await db.commit()
    await db.refresh(campaign)

    logger.info(
        "campaign_started",
        campaign_id=str(campaign_id),
        enqueued=enqueued,
        concurrency_limit=campaign.concurrency_limit,
    )
    return campaign


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Pause a running campaign."""
    campaign = await _get_campaign_or_404(campaign_id, org_id, db)

    if campaign.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pause campaign with status '{campaign.status}'. Must be 'running'.",
        )

    campaign.status = "paused"
    await db.commit()
    await db.refresh(campaign)

    logger.info("campaign_paused", campaign_id=str(campaign_id))
    return campaign


@router.post("/{campaign_id}/cancel", response_model=CampaignResponse)
async def cancel_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a campaign. Sets remaining queued leads to cancelled."""
    campaign = await _get_campaign_or_404(campaign_id, org_id, db)

    if campaign.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Campaign is already '{campaign.status}'.",
        )

    campaign.status = "cancelled"

    # Cancel all queued campaign_leads (both "queued" and "processing" that haven't started)
    await db.execute(
        update(CampaignLead)
        .where(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.status.in_(["queued", "processing"]),
        )
        .values(status="cancelled")
    )

    # Cancel any pending call_queue entries for this campaign
    await db.execute(
        update(QueuedCall)
        .where(
            QueuedCall.campaign_id == campaign_id,
            QueuedCall.status == "queued",
        )
        .values(status="cancelled")
    )

    await db.commit()
    await db.refresh(campaign)

    logger.info("campaign_cancelled", campaign_id=str(campaign_id))
    return campaign


@router.get("/{campaign_id}/leads", response_model=PaginatedCampaignLeads)
async def list_campaign_leads(
    campaign_id: uuid.UUID,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List leads in a campaign with their campaign-specific status."""
    # Verify campaign belongs to org
    await _get_campaign_or_404(campaign_id, org_id, db)

    base = (
        select(
            CampaignLead,
            Lead.phone_number,
            Lead.contact_name,
            Lead.email,
            Lead.company,
        )
        .join(Lead, CampaignLead.lead_id == Lead.id)
        .where(CampaignLead.campaign_id == campaign_id)
    )

    if status:
        base = base.where(CampaignLead.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = base.order_by(CampaignLead.position).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(rows_q)
    rows = result.all()

    items = [
        CampaignLeadResponse(
            id=cl.id,
            campaign_id=cl.campaign_id,
            lead_id=cl.lead_id,
            status=cl.status,
            call_log_id=cl.call_log_id,
            position=cl.position,
            retry_count=cl.retry_count,
            created_at=cl.created_at,
            processed_at=cl.processed_at,
            phone_number=phone_number,
            contact_name=contact_name,
            email=email,
            company=company,
        )
        for cl, phone_number, contact_name, email, company in rows
    ]

    return PaginatedCampaignLeads(items=items, total=total, page=page, page_size=page_size)
