"""REST API for messaging provider management (WhatsApp/SMS credentials)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.config import settings
from app.database import get_db
from app.models.messaging_provider import MessagingProvider
from app.models.user import User
from app.services.credential_encryption import encrypt_credentials

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/messaging", tags=["messaging"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ProviderCreate(BaseModel):
    name: str
    provider_type: str  # wati, aisensy, twilio_whatsapp, twilio_sms
    credentials: dict[str, Any]  # plaintext creds — will be encrypted before storage
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    credentials: dict[str, Any] | None = None
    is_default: bool | None = None


class ProviderResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider_type: str
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List all messaging providers for the current organisation."""
    result = await db.execute(
        select(MessagingProvider)
        .where(MessagingProvider.org_id == org_id)
        .order_by(MessagingProvider.created_at.desc())
    )
    return result.scalars().all()


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def create_provider(
    body: ProviderCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a messaging provider with encrypted credentials."""
    encrypted = encrypt_credentials(body.credentials, settings.MESSAGING_CREDENTIALS_KEY)

    # If setting as default, unset other defaults for this org
    if body.is_default:
        existing = await db.execute(
            select(MessagingProvider).where(
                MessagingProvider.org_id == org_id, MessagingProvider.is_default == True
            )
        )
        for prov in existing.scalars().all():
            prov.is_default = False

    provider = MessagingProvider(
        org_id=org_id,
        name=body.name,
        provider_type=body.provider_type,
        credentials=encrypted,
        is_default=body.is_default,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info("messaging_provider_created", provider_id=str(provider.id), org_id=str(org_id))
    return provider


@router.put("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update a messaging provider."""
    result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.id == provider_id, MessagingProvider.org_id == org_id
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    update_data = body.model_dump(exclude_unset=True)

    # Encrypt credentials if being updated
    if "credentials" in update_data and update_data["credentials"] is not None:
        update_data["credentials"] = encrypt_credentials(
            update_data["credentials"], settings.MESSAGING_CREDENTIALS_KEY
        )

    # If setting as default, unset other defaults
    if update_data.get("is_default"):
        existing = await db.execute(
            select(MessagingProvider).where(
                MessagingProvider.org_id == org_id,
                MessagingProvider.is_default == True,
                MessagingProvider.id != provider_id,
            )
        )
        for prov in existing.scalars().all():
            prov.is_default = False

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.commit()
    await db.refresh(provider)

    logger.info("messaging_provider_updated", provider_id=str(provider_id), fields=list(update_data.keys()))
    return provider


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete a messaging provider."""
    result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.id == provider_id, MessagingProvider.org_id == org_id
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    await db.delete(provider)
    await db.commit()

    logger.info("messaging_provider_deleted", provider_id=str(provider_id), org_id=str(org_id))


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Test a messaging provider connection (placeholder)."""
    result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.id == provider_id, MessagingProvider.org_id == org_id
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    return {"success": True, "message": "Connection test not yet implemented"}
