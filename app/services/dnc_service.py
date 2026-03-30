"""Do Not Call service — check, add, remove DNC entries.

All phone numbers are normalized via normalize_phone() before any DB operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.do_not_call import DoNotCall
from app.utils import normalize_phone

logger = structlog.get_logger(__name__)


async def check_dnc(
    db: AsyncSession,
    org_id: uuid.UUID,
    phone: str,
) -> bool:
    """Return True if this phone is on the active DNC list for this org."""
    normalized = normalize_phone(phone)
    result = await db.execute(
        select(DoNotCall.id)
        .where(
            DoNotCall.org_id == org_id,
            DoNotCall.phone_number == normalized,
            DoNotCall.removed_at.is_(None),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def has_manual_override(
    db: AsyncSession,
    org_id: uuid.UUID,
    phone: str,
) -> bool:
    """Return True if a manual override exists for this phone (including removed rows)."""
    normalized = normalize_phone(phone)
    result = await db.execute(
        select(DoNotCall.id)
        .where(
            DoNotCall.org_id == org_id,
            DoNotCall.phone_number == normalized,
            DoNotCall.manual_override.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def add_dnc(
    db: AsyncSession,
    org_id: uuid.UUID,
    phone: str,
    reason: str,
    source: str,
    source_call_log_id: uuid.UUID | None = None,
    created_by: str = "system",
) -> DoNotCall | None:
    """Add a phone to the DNC list. Returns the entry, or None if already exists.

    Uses ON CONFLICT DO NOTHING for idempotent concurrent adds.
    """
    normalized = normalize_phone(phone)

    stmt = (
        pg_insert(DoNotCall)
        .values(
            org_id=org_id,
            phone_number=normalized,
            reason=reason,
            source=source,
            source_call_log_id=source_call_log_id,
            created_by=created_by,
        )
        .on_conflict_do_nothing(
            index_elements=["org_id", "phone_number"],
            index_where=DoNotCall.removed_at.is_(None),
        )
        .returning(DoNotCall)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry:
        logger.info(
            "dnc_added",
            org_id=str(org_id),
            phone=normalized,
            source=source,
            reason=reason,
        )
    else:
        logger.info("dnc_already_exists", org_id=str(org_id), phone=normalized)

    return entry


async def remove_dnc(
    db: AsyncSession,
    org_id: uuid.UUID,
    phone: str,
    removed_by: str,
) -> bool:
    """Soft-delete the active DNC entry and set manual_override=True.

    Returns True if an entry was removed, False if no active entry found.
    """
    normalized = normalize_phone(phone)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        update(DoNotCall)
        .where(
            DoNotCall.org_id == org_id,
            DoNotCall.phone_number == normalized,
            DoNotCall.removed_at.is_(None),
        )
        .values(
            removed_at=now,
            removed_by=removed_by,
            manual_override=True,
        )
        .returning(DoNotCall.id)
    )
    removed = result.scalar_one_or_none()

    if removed:
        logger.info(
            "dnc_removed",
            org_id=str(org_id),
            phone=normalized,
            removed_by=removed_by,
        )
        return True

    return False


async def get_dnc_status(
    db: AsyncSession,
    org_id: uuid.UUID,
    phone: str,
) -> DoNotCall | None:
    """Return the active DNC entry for this phone, or None."""
    normalized = normalize_phone(phone)
    result = await db.execute(
        select(DoNotCall).where(
            DoNotCall.org_id == org_id,
            DoNotCall.phone_number == normalized,
            DoNotCall.removed_at.is_(None),
        )
    )
    return result.scalar_one_or_none()
