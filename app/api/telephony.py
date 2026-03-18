"""API endpoints for org-level telephony configuration and phone numbers."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import update

from app.auth.dependencies import get_current_user, get_current_org, require_role
from app.database import get_db
from app.models.bot_config import BotConfig
from app.models.organization import Organization
from app.models.phone_number import PhoneNumber
from app.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/telephony", tags=["telephony"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TelephonyConfigResponse(BaseModel):
    plivo_auth_id: str | None = None
    plivo_auth_token_set: bool = False
    twilio_account_sid: str | None = None
    twilio_auth_token_set: bool = False
    ghl_api_key_set: bool = False
    ghl_location_id: str | None = None


class UpdateTelephonyConfigRequest(BaseModel):
    plivo_auth_id: str | None = None
    plivo_auth_token: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    ghl_api_key: str | None = None
    ghl_location_id: str | None = None


class PhoneNumberResponse(BaseModel):
    id: uuid.UUID
    provider: str
    phone_number: str
    label: str | None
    is_default: bool

    model_config = {"from_attributes": True}


class CreatePhoneNumberRequest(BaseModel):
    provider: str  # "plivo" or "twilio"
    phone_number: str
    label: str | None = None
    is_default: bool = False


class UpdatePhoneNumberRequest(BaseModel):
    label: str | None = None
    is_default: bool | None = None


# ---------------------------------------------------------------------------
# Telephony config endpoints
# ---------------------------------------------------------------------------


@router.get("/config", response_model=TelephonyConfigResponse)
async def get_telephony_config(
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get org-level telephony credentials (tokens masked)."""
    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one()

    return TelephonyConfigResponse(
        plivo_auth_id=org.plivo_auth_id,
        plivo_auth_token_set=bool(org.plivo_auth_token),
        twilio_account_sid=org.twilio_account_sid,
        twilio_auth_token_set=bool(org.twilio_auth_token),
        ghl_api_key_set=bool(org.ghl_api_key),
        ghl_location_id=org.ghl_location_id,
    )


@router.patch("/config", response_model=TelephonyConfigResponse)
async def update_telephony_config(
    req: UpdateTelephonyConfigRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update org-level telephony credentials."""
    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one()

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)

    await db.commit()
    await db.refresh(org)

    logger.info("telephony_config_updated", org_id=str(org.id), fields=list(update_data.keys()))

    return TelephonyConfigResponse(
        plivo_auth_id=org.plivo_auth_id,
        plivo_auth_token_set=bool(org.plivo_auth_token),
        twilio_account_sid=org.twilio_account_sid,
        twilio_auth_token_set=bool(org.twilio_auth_token),
        ghl_api_key_set=bool(org.ghl_api_key),
        ghl_location_id=org.ghl_location_id,
    )


# ---------------------------------------------------------------------------
# Phone number endpoints
# ---------------------------------------------------------------------------


@router.get("/phone-numbers", response_model=list[PhoneNumberResponse])
async def list_phone_numbers(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """List all phone numbers for the current org."""
    result = await db.execute(
        select(PhoneNumber)
        .where(PhoneNumber.org_id == org_id)
        .order_by(PhoneNumber.is_default.desc(), PhoneNumber.created_at)
    )
    return result.scalars().all()


@router.post("/phone-numbers", response_model=PhoneNumberResponse, status_code=201)
async def create_phone_number(
    req: CreatePhoneNumberRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Add a phone number to the org."""
    if req.provider not in ("plivo", "twilio"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be 'plivo' or 'twilio'",
        )

    # If this is set as default, unset other defaults for same provider
    if req.is_default:
        existing = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.org_id == user.org_id,
                PhoneNumber.provider == req.provider,
                PhoneNumber.is_default == True,
            )
        )
        for pn in existing.scalars().all():
            pn.is_default = False

    phone = PhoneNumber(
        org_id=user.org_id,
        provider=req.provider,
        phone_number=req.phone_number,
        label=req.label,
        is_default=req.is_default,
    )
    db.add(phone)
    await db.commit()
    await db.refresh(phone)

    logger.info("phone_number_created", phone_id=str(phone.id), org_id=str(user.org_id))
    return phone


@router.patch("/phone-numbers/{phone_id}", response_model=PhoneNumberResponse)
async def update_phone_number(
    phone_id: uuid.UUID,
    req: UpdatePhoneNumberRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a phone number's label or default status."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == phone_id, PhoneNumber.org_id == user.org_id)
    )
    phone = result.scalar_one_or_none()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    update_data = req.model_dump(exclude_unset=True)

    # If setting as default, unset other defaults for same provider
    if update_data.get("is_default"):
        existing = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.org_id == user.org_id,
                PhoneNumber.provider == phone.provider,
                PhoneNumber.is_default == True,
                PhoneNumber.id != phone_id,
            )
        )
        for pn in existing.scalars().all():
            pn.is_default = False

    for field, value in update_data.items():
        setattr(phone, field, value)

    await db.commit()
    await db.refresh(phone)
    return phone


@router.delete("/phone-numbers/{phone_id}", status_code=204)
async def delete_phone_number(
    phone_id: uuid.UUID,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a phone number."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == phone_id, PhoneNumber.org_id == user.org_id)
    )
    phone = result.scalar_one_or_none()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    # Nullify phone_number_id on any bots referencing this number
    await db.execute(
        update(BotConfig)
        .where(BotConfig.phone_number_id == phone_id)
        .values(phone_number_id=None)
    )

    await db.delete(phone)
    await db.commit()
    logger.info("phone_number_deleted", phone_id=str(phone_id), org_id=str(user.org_id))
