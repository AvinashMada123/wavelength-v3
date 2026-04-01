"""Lead engagement tracking service.

Stores Gemini extraction data and per-touchpoint message analytics
for the personalized engagement flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_engagement import LeadEngagement

logger = structlog.get_logger(__name__)

VALID_TOUCHPOINT_KEYS = frozenset({
    "t1_wa", "t1_email",
    "t2_wa", "t2_email",
    "t3_wa", "t3_email",
    "t4_wa", "t4_email",
    "t5_wa", "t5_email",
    "t6_wa", "t6_email",
    "t7_wa", "t7_email",
    "t8_wa", "t8_email",
})


async def create_engagement(
    db: AsyncSession,
    org_id: uuid.UUID,
    call_log_id: uuid.UUID,
    contact_phone: str,
    contact_email: str | None,
    extraction_data: dict,
    ghl_contact_id: str | None = None,
) -> LeadEngagement:
    """Create a new engagement record after Gemini extraction."""
    engagement = LeadEngagement(
        org_id=org_id,
        call_log_id=call_log_id,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extraction_data=extraction_data or {},
        ghl_contact_id=ghl_contact_id,
    )
    db.add(engagement)
    await db.commit()
    await db.refresh(engagement)
    logger.info(
        "engagement_created",
        engagement_id=str(engagement.id),
        call_log_id=str(call_log_id),
        phone=contact_phone,
    )
    return engagement


async def update_touchpoint(
    db: AsyncSession,
    call_log_id: uuid.UUID,
    touchpoint_key: str,
    message_data: dict,
) -> LeadEngagement | None:
    """Update a specific touchpoint's message data after send."""
    if touchpoint_key not in VALID_TOUCHPOINT_KEYS:
        logger.warning("invalid_touchpoint_key", key=touchpoint_key)
        return None

    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    engagement = result.scalar_one_or_none()
    if not engagement:
        logger.warning("engagement_not_found_for_touchpoint", call_log_id=str(call_log_id))
        return None

    tp = dict(engagement.touchpoints or {})
    tp[touchpoint_key] = {
        **message_data,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    engagement.touchpoints = tp
    engagement.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "touchpoint_updated",
        call_log_id=str(call_log_id),
        touchpoint=touchpoint_key,
        status=message_data.get("status"),
    )
    return engagement


async def update_report_link(
    db: AsyncSession,
    call_log_id: uuid.UUID,
    report_link: str,
) -> LeadEngagement | None:
    """Set the report PDF link after GCS upload."""
    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    engagement = result.scalar_one_or_none()
    if not engagement:
        logger.warning("engagement_not_found_for_report", call_log_id=str(call_log_id))
        return None

    engagement.report_link = report_link
    engagement.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("report_link_updated", call_log_id=str(call_log_id))
    return engagement


async def get_engagement(
    db: AsyncSession,
    call_log_id: uuid.UUID,
) -> LeadEngagement | None:
    """Retrieve engagement by call_log_id."""
    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    return result.scalar_one_or_none()


async def get_engagement_by_phone(
    db: AsyncSession,
    org_id: uuid.UUID,
    contact_phone: str,
) -> LeadEngagement | None:
    """Retrieve most recent engagement by phone number."""
    result = await db.execute(
        select(LeadEngagement)
        .where(
            LeadEngagement.org_id == org_id,
            LeadEngagement.contact_phone == contact_phone,
        )
        .order_by(LeadEngagement.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
