"""Auto-create and update leads when calls are triggered and completed."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead

logger = structlog.get_logger(__name__)


async def find_or_create_lead(
    db: AsyncSession,
    org_id,
    phone_number: str,
    contact_name: str,
    ghl_contact_id: str | None = None,
    source: str = "auto_call",
    extra_vars: dict[str, str] | None = None,
) -> Lead:
    """Find an existing lead by (org_id, phone_number) or create one.

    Saves extra_vars (event_name, location, etc.) into custom_fields so they
    persist across callbacks and manual re-calls.

    Returns the Lead instance (already flushed with an ID).
    """
    result = await db.execute(
        select(Lead).where(
            Lead.org_id == org_id,
            Lead.phone_number == phone_number,
        )
    )
    lead = result.scalar_one_or_none()

    if lead:
        # Update ghl_contact_id if we have one and lead doesn't
        if ghl_contact_id and not lead.ghl_contact_id:
            lead.ghl_contact_id = ghl_contact_id
        # Merge new extra_vars into existing custom_fields (new values win)
        if extra_vars:
            merged = dict(lead.custom_fields or {})
            merged.update(extra_vars)
            lead.custom_fields = merged
        logger.info(
            "lead_found",
            lead_id=str(lead.id),
            phone=phone_number,
        )
        return lead

    # Create new lead
    lead = Lead(
        org_id=org_id,
        phone_number=phone_number,
        contact_name=contact_name,
        ghl_contact_id=ghl_contact_id,
        custom_fields=extra_vars or {},
        source=source,
        status="new",
    )
    db.add(lead)
    await db.flush()

    logger.info(
        "lead_auto_created",
        lead_id=str(lead.id),
        phone=phone_number,
        org_id=str(org_id),
    )
    return lead


async def update_lead_after_call(
    db: AsyncSession,
    org_id,
    contact_phone: str,
    summary: str | None = None,
    qualification_level: str | None = None,
    call_log_id=None,
) -> None:
    """Update lead stats after a call completes.

    Increments call_count, sets last_call_date, updates qualification and bot_notes.
    """
    result = await db.execute(
        select(Lead).where(
            Lead.org_id == org_id,
            Lead.phone_number == contact_phone,
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        logger.warning(
            "lead_not_found_for_update",
            phone=contact_phone,
            org_id=str(org_id),
        )
        return

    lead.call_count = (lead.call_count or 0) + 1
    lead.last_call_date = datetime.now(timezone.utc)

    if qualification_level:
        lead.qualification_level = qualification_level

    # Update status from "new" to "contacted" after first completed call
    if lead.status == "new":
        lead.status = "contacted"

    if summary:
        lead.bot_notes = summary

    lead.updated_at = datetime.now(timezone.utc)

    logger.info(
        "lead_updated_after_call",
        lead_id=str(lead.id),
        call_count=lead.call_count,
        qualification=qualification_level,
    )
