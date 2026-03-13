"""Payments API — Cashfree payment gateway integration for self-service credit purchase."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import aiohttp
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.billing import CreditTransaction, PaymentOrder
from app.models.organization import Organization
from app.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])

CREDIT_PRICE_INR = Decimal("4.5")


def _cashfree_base_url() -> str:
    if settings.CASHFREE_ENVIRONMENT == "PRODUCTION":
        return "https://api.cashfree.com/pg"
    return "https://sandbox.cashfree.com/pg"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    credits: int = Field(ge=10, le=10000, description="Number of credits to purchase")
    phone: str = Field(default="9999999999", description="Customer phone for Cashfree")


class CreateOrderResponse(BaseModel):
    order_id: str
    payment_session_id: str
    amount: float
    cf_environment: str


class VerifyPaymentResponse(BaseModel):
    order_id: str
    status: str
    credits: float
    amount: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _cashfree_request(method: str, path: str, payload: dict | None = None) -> dict:
    """Make an authenticated request to Cashfree API."""
    headers = {
        "x-client-id": settings.CASHFREE_APP_ID,
        "x-client-secret": settings.CASHFREE_SECRET_KEY,
        "x-api-version": "2023-08-01",
        "Content-Type": "application/json",
    }
    url = f"{_cashfree_base_url()}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=headers, json=payload) as resp:
            data = await resp.json()
            if resp.status >= 400:
                logger.error("cashfree_api_error", status=resp.status, body=data, path=path)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Payment gateway error: {data.get('message', 'Unknown error')}",
                )
            return data


def _verify_webhook_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Cashfree webhook signature using HMAC-SHA256."""
    raw_payload = timestamp + body.decode("utf-8")
    computed = hmac.new(
        settings.CASHFREE_SECRET_KEY.encode("utf-8"),
        raw_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    computed_b64 = base64.b64encode(computed).decode("utf-8")
    return hmac.compare_digest(computed_b64, signature)


async def _process_successful_payment(
    db: AsyncSession,
    payment_order: PaymentOrder,
    payment_data: dict,
) -> None:
    """Add credits to org and mark payment as paid. Uses row-level lock."""
    # Row-lock the org to prevent concurrent credit updates
    result = await db.execute(
        select(Organization)
        .where(Organization.id == payment_order.org_id)
        .with_for_update()
    )
    org = result.scalar_one()

    new_balance = org.credit_balance + payment_order.credits
    org.credit_balance = new_balance

    # Create credit transaction record
    tx = CreditTransaction(
        org_id=payment_order.org_id,
        amount=payment_order.credits,
        balance_after=new_balance,
        type="topup",
        description=f"Cashfree payment — {payment_order.credits} credits (Order: {payment_order.order_id})",
        reference_id=str(payment_order.id),
        created_by=payment_order.user_id,
    )
    db.add(tx)

    # Update payment order
    payment_order.status = "paid"
    payment_order.payment_method = (
        payment_data.get("payment_method") or payment_data.get("payment_group")
    )
    payment_order.cf_payment_id = str(payment_data.get("cf_payment_id", "")) or None
    payment_order.updated_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "payment_processed",
        order_id=payment_order.order_id,
        credits=str(payment_order.credits),
        new_balance=str(new_balance),
        org_id=str(payment_order.org_id),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(
    req: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Cashfree payment order for credit purchase."""
    amount = Decimal(req.credits) * CREDIT_PRICE_INR
    order_id = f"WL-{uuid.uuid4().hex[:12].upper()}"

    # Create order via Cashfree API
    cf_data = await _cashfree_request("POST", "/orders", payload={
        "order_id": order_id,
        "order_amount": float(amount),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": str(user.id),
            "customer_email": user.email,
            "customer_name": user.display_name,
            "customer_phone": req.phone,
        },
        "order_meta": {
            "return_url": f"{settings.PUBLIC_BASE_URL}/billing?order_id={order_id}",
            "notify_url": f"{settings.PUBLIC_BASE_URL}/api/payments/webhook",
        },
    })

    # Persist order in our DB
    payment_order = PaymentOrder(
        org_id=user.org_id,
        user_id=user.id,
        order_id=order_id,
        cf_order_id=cf_data.get("cf_order_id", ""),
        amount_inr=amount,
        credits=Decimal(req.credits),
        status="created",
    )
    db.add(payment_order)
    await db.commit()

    logger.info(
        "payment_order_created",
        order_id=order_id,
        credits=req.credits,
        amount=float(amount),
        user_id=str(user.id),
        org_id=str(user.org_id),
    )

    return CreateOrderResponse(
        order_id=order_id,
        payment_session_id=cf_data["payment_session_id"],
        amount=float(amount),
        cf_environment=settings.CASHFREE_ENVIRONMENT.lower(),
    )


@router.post("/webhook")
async def cashfree_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Cashfree payment webhooks. No auth — called by Cashfree servers."""
    body = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")

    if not _verify_webhook_signature(body, timestamp, signature):
        logger.warning("webhook_signature_invalid")
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body)
    event_type = payload.get("type")
    order_data = payload.get("data", {}).get("order", {})
    payment_data = payload.get("data", {}).get("payment", {})
    order_id = order_data.get("order_id")

    if not order_id:
        return {"status": "ignored"}

    logger.info("webhook_received", event_type=event_type, order_id=order_id)

    # Fetch our payment order
    result = await db.execute(
        select(PaymentOrder).where(PaymentOrder.order_id == order_id)
    )
    payment_order = result.scalar_one_or_none()

    if not payment_order:
        logger.warning("webhook_order_not_found", order_id=order_id)
        return {"status": "not_found"}

    if event_type == "PAYMENT_SUCCESS_WEBHOOK":
        # Idempotent — skip if already processed
        if payment_order.status == "paid":
            return {"status": "already_processed"}

        # Verify amount matches
        webhook_amount = Decimal(str(order_data.get("order_amount", 0)))
        if webhook_amount != payment_order.amount_inr:
            logger.error(
                "webhook_amount_mismatch",
                order_id=order_id,
                expected=str(payment_order.amount_inr),
                received=str(webhook_amount),
            )
            raise HTTPException(status_code=400, detail="Amount mismatch")

        await _process_successful_payment(db, payment_order, payment_data)

    elif event_type in ("PAYMENT_FAILED_WEBHOOK", "PAYMENT_USER_DROPPED_WEBHOOK"):
        payment_order.status = "failed"
        payment_order.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {"status": "ok"}


@router.get("/verify/{order_id}", response_model=VerifyPaymentResponse)
async def verify_payment(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify payment status — safety net for missed webhooks."""
    result = await db.execute(
        select(PaymentOrder).where(
            PaymentOrder.order_id == order_id,
            PaymentOrder.org_id == user.org_id,
        )
    )
    payment_order = result.scalar_one_or_none()

    if not payment_order:
        raise HTTPException(status_code=404, detail="Order not found")

    # If already processed, return current status
    if payment_order.status == "paid":
        return VerifyPaymentResponse(
            order_id=order_id,
            status="paid",
            credits=float(payment_order.credits),
            amount=float(payment_order.amount_inr),
        )

    # Check with Cashfree for latest status (safety net for missed webhooks)
    cf_data = await _cashfree_request("GET", f"/orders/{order_id}")
    cf_status = cf_data.get("order_status")

    if cf_status == "PAID" and payment_order.status != "paid":
        payment_info = cf_data.get("payment", {}) if isinstance(cf_data.get("payment"), dict) else {}
        await _process_successful_payment(db, payment_order, payment_info)
    elif cf_status in ("EXPIRED", "TERMINATED"):
        payment_order.status = "expired"
        payment_order.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return VerifyPaymentResponse(
        order_id=order_id,
        status=payment_order.status,
        credits=float(payment_order.credits),
        amount=float(payment_order.amount_inr),
    )
