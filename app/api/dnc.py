"""Do Not Call API endpoints."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user, require_role
from app.database import get_db
from app.models.do_not_call import DoNotCall
from app.models.user import User
from app.services.dnc_service import add_dnc, check_dnc, get_dnc_status, remove_dnc
from app.utils import normalize_phone

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/dnc", tags=["do-not-call"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DncCheckResponse(BaseModel):
    phone_number: str
    is_blocked: bool
    reason: str | None = None
    source: str | None = None
    created_at: str | None = None
    created_by: str | None = None


class DncAddRequest(BaseModel):
    phone: str
    reason: str


class DncRemoveRequest(BaseModel):
    phone: str


class DncListItem(BaseModel):
    id: str
    phone_number: str
    reason: str
    source: str
    created_by: str
    created_at: str
    source_call_log_id: str | None = None


class DncListResponse(BaseModel):
    total: int
    items: list[DncListItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/check")
async def dnc_check(
    phone: str = Query(..., description="Phone number to check"),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> DncCheckResponse:
    """Check if a phone number is on the DNC list."""
    entry = await get_dnc_status(db, org_id, phone)
    if entry:
        return DncCheckResponse(
            phone_number=entry.phone_number,
            is_blocked=True,
            reason=entry.reason,
            source=entry.source,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
            created_by=entry.created_by,
        )
    return DncCheckResponse(
        phone_number=normalize_phone(phone),
        is_blocked=False,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def dnc_add(
    body: DncAddRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
) -> DncCheckResponse:
    """Manually add a phone number to the DNC list. Admin only."""
    entry = await add_dnc(
        db,
        org_id=user.org_id,
        phone=body.phone,
        reason=f"manual: {body.reason}",
        source="manual_ui",
        created_by=user.email,
    )
    await db.commit()

    if entry:
        return DncCheckResponse(
            phone_number=entry.phone_number,
            is_blocked=True,
            reason=entry.reason,
            source=entry.source,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
            created_by=entry.created_by,
        )

    # Already existed — return current status
    existing = await get_dnc_status(db, user.org_id, body.phone)
    if existing:
        return DncCheckResponse(
            phone_number=existing.phone_number,
            is_blocked=True,
            reason=existing.reason,
            source=existing.source,
            created_at=existing.created_at.isoformat() if existing.created_at else None,
            created_by=existing.created_by,
        )

    raise HTTPException(status_code=500, detail="Failed to add DNC entry")


@router.delete("")
async def dnc_remove(
    body: DncRemoveRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
) -> DncCheckResponse:
    """Remove a phone number from the DNC list. Admin only. Sets manual_override."""
    removed = await remove_dnc(db, user.org_id, body.phone, removed_by=user.email)
    await db.commit()

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active DNC entry found for this phone number",
        )

    return DncCheckResponse(
        phone_number=normalize_phone(body.phone),
        is_blocked=False,
        reason=None,
        source=None,
    )


@router.get("/list")
async def dnc_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> DncListResponse:
    """List all active DNC entries for the org. Paginated."""
    # Count
    count_result = await db.execute(
        select(func.count(DoNotCall.id)).where(
            DoNotCall.org_id == org_id,
            DoNotCall.removed_at.is_(None),
        )
    )
    total = count_result.scalar() or 0

    # Fetch page
    offset = (page - 1) * page_size
    result = await db.execute(
        select(DoNotCall)
        .where(DoNotCall.org_id == org_id, DoNotCall.removed_at.is_(None))
        .order_by(DoNotCall.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    entries = result.scalars().all()

    items = [
        DncListItem(
            id=str(e.id),
            phone_number=e.phone_number,
            reason=e.reason,
            source=e.source,
            created_by=e.created_by,
            created_at=e.created_at.isoformat(),
            source_call_log_id=str(e.source_call_log_id) if e.source_call_log_id else None,
        )
        for e in entries
    ]

    return DncListResponse(total=total, items=items)
