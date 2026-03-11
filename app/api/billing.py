"""Billing API — credit balance, transaction history, and admin credit management."""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.billing import CreditTransaction
from app.models.organization import Organization
from app.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class BalanceResponse(BaseModel):
    balance: float
    org_id: uuid.UUID


class TransactionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    amount: float
    balance_after: float
    type: str
    description: str
    reference_id: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int


class AddCreditsRequest(BaseModel):
    org_id: uuid.UUID
    amount: Decimal = Field(gt=0, description="Number of credits to add (must be positive)")
    description: str | None = None


class AdjustCreditsRequest(BaseModel):
    org_id: uuid.UUID
    amount: Decimal = Field(description="Credits to adjust (positive or negative)")
    description: str | None = None


class CreditBalanceResponse(BaseModel):
    org_id: uuid.UUID
    balance: float


class OrgBalanceResponse(BaseModel):
    org_id: uuid.UUID
    org_name: str
    credit_balance: float


# ---------------------------------------------------------------------------
# Authenticated user endpoints
# ---------------------------------------------------------------------------


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current organization's credit balance."""
    result = await db.execute(
        select(Organization.credit_balance).where(Organization.id == user.org_id)
    )
    balance = result.scalar_one_or_none()

    if balance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return BalanceResponse(balance=float(balance), org_id=user.org_id)


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    type: str | None = Query(None, description="Filter by transaction type"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated credit transaction history for the current organization."""
    base_filter = CreditTransaction.org_id == user.org_id
    filters = [base_filter]

    if type is not None:
        filters.append(CreditTransaction.type == type)

    # Total count
    count_stmt = select(func.count(CreditTransaction.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    # Paginated results
    offset = (page - 1) * page_size
    stmt = (
        select(CreditTransaction)
        .where(*filters)
        .order_by(CreditTransaction.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return TransactionListResponse(
        items=[
            TransactionResponse(
                id=tx.id,
                org_id=tx.org_id,
                amount=float(tx.amount),
                balance_after=float(tx.balance_after),
                type=tx.type,
                description=tx.description,
                reference_id=tx.reference_id,
                created_by=tx.created_by,
                created_at=tx.created_at,
            )
            for tx in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Admin endpoints (super_admin only)
# ---------------------------------------------------------------------------


@router.post("/admin/add-credits", response_model=CreditBalanceResponse)
async def add_credits(
    req: AddCreditsRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Add credits to an organization (super admin only)."""
    # Fetch the org
    result = await db.execute(
        select(Organization).where(Organization.id == req.org_id)
    )
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    new_balance = org.credit_balance + req.amount

    # Update the org balance
    org.credit_balance = new_balance

    # Create transaction record
    tx = CreditTransaction(
        org_id=req.org_id,
        amount=req.amount,
        balance_after=new_balance,
        type="topup",
        description=req.description or f"Manual topup by admin ({user.email})",
        created_by=user.id,
    )
    db.add(tx)

    await db.commit()

    logger.info(
        "credits_added",
        org_id=str(req.org_id),
        amount=req.amount,
        new_balance=new_balance,
        by=str(user.id),
    )

    return CreditBalanceResponse(org_id=req.org_id, balance=float(new_balance))


@router.post("/admin/adjust-credits", response_model=CreditBalanceResponse)
async def adjust_credits(
    req: AdjustCreditsRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Adjust credits for an organization — can be positive or negative (super admin only)."""
    if req.amount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Adjustment amount cannot be zero",
        )

    # Fetch the org
    result = await db.execute(
        select(Organization).where(Organization.id == req.org_id)
    )
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    new_balance = org.credit_balance + req.amount

    # Update the org balance
    org.credit_balance = new_balance

    # Create transaction record
    tx = CreditTransaction(
        org_id=req.org_id,
        amount=req.amount,
        balance_after=new_balance,
        type="adjustment",
        description=req.description or f"Manual adjustment by admin ({user.email})",
        created_by=user.id,
    )
    db.add(tx)

    await db.commit()

    logger.info(
        "credits_adjusted",
        org_id=str(req.org_id),
        amount=req.amount,
        new_balance=new_balance,
        by=str(user.id),
    )

    return CreditBalanceResponse(org_id=req.org_id, balance=float(new_balance))


@router.get("/admin/org-balances", response_model=list[OrgBalanceResponse])
async def get_org_balances(
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get credit balances for all organizations (super admin only)."""
    result = await db.execute(
        select(Organization.id, Organization.name, Organization.credit_balance)
        .order_by(Organization.name)
    )
    rows = result.all()

    return [
        OrgBalanceResponse(
            org_id=row.id,
            org_name=row.name,
            credit_balance=float(row.credit_balance),
        )
        for row in rows
    ]
