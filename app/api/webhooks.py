"""Inbound webhooks for messaging provider callbacks (WhatsApp replies, etc.)."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import sequence_engine

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/whatsapp-reply/{provider_id}")
async def whatsapp_reply(
    provider_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle incoming WhatsApp reply webhook from WATI/AISensy.

    Normalizes the phone number and delegates to the sequence engine's
    reply handler.

    TODO: Add HMAC signature verification for webhook authenticity.
    """
    body = await request.json()

    # Normalize phone — WATI sends `waId`, AISensy sends `senderPhone` or `from`
    phone = (
        body.get("waId")
        or body.get("senderPhone")
        or body.get("from")
        or body.get("phone")
        or ""
    )
    # Strip non-digit chars except leading +
    phone = phone.lstrip("+")

    # Extract message text — different providers use different keys
    message_text = (
        body.get("text")
        or body.get("message")
        or body.get("messageText")
        or body.get("body")
        or ""
    )

    if not phone or not message_text:
        logger.warning(
            "whatsapp_reply_missing_fields",
            provider_id=str(provider_id),
            has_phone=bool(phone),
            has_text=bool(message_text),
        )
        return {"ok": True, "processed": False}

    logger.info(
        "whatsapp_reply_received",
        provider_id=str(provider_id),
        phone=phone[-4:],  # Log last 4 digits only
    )

    processed = await sequence_engine.handle_reply(db, phone, message_text)

    return {"ok": True, "processed": processed}
