from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import CreditTransaction
from app.models.call_log import CallLog
from app.models.organization import Organization

logger = structlog.get_logger(__name__)
ZERO_CREDITS = Decimal("0.00")
PER_MINUTE_RATE = Decimal("1.00")
SECONDS_PER_MINUTE = Decimal("60")
CENT_PRECISION = Decimal("0.01")
# Minimum balance required to start a new call (1 minute worth of credits)
MIN_BALANCE_TO_CALL = PER_MINUTE_RATE


async def check_org_credits(db: AsyncSession, org_id) -> tuple[bool, Decimal]:
    """Check if an org has enough credits to start a call.

    Returns (has_credits, current_balance).
    """
    result = await db.execute(
        select(Organization.credit_balance).where(Organization.id == org_id)
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        return False, ZERO_CREDITS
    return balance >= MIN_BALANCE_TO_CALL, balance


def calculate_call_credits(duration_seconds: int | None) -> Decimal:
    """Charge prorated credits at 1 credit per minute, rounded to 2 decimals."""
    if duration_seconds is None or duration_seconds <= 0:
        return ZERO_CREDITS
    return (
        Decimal(duration_seconds) * PER_MINUTE_RATE / SECONDS_PER_MINUTE
    ).quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)


def resolve_call_duration_seconds(
    call_log: CallLog,
    reported_duration_seconds: int | None = None,
) -> int | None:
    """Prefer provider-reported duration, then stored call metrics, then timestamps."""
    if reported_duration_seconds is not None and reported_duration_seconds > 0:
        return reported_duration_seconds

    if call_log.call_duration is not None and call_log.call_duration > 0:
        return call_log.call_duration

    metadata = call_log.metadata_ or {}
    metric_duration = (metadata.get("call_metrics") or {}).get("total_duration_s")
    if isinstance(metric_duration, int) and metric_duration > 0:
        return metric_duration

    if call_log.started_at and call_log.ended_at:
        elapsed = int((call_log.ended_at - call_log.started_at).total_seconds())
        if elapsed > 0:
            return elapsed

    return None


async def bill_completed_call(
    db: AsyncSession,
    call_log: CallLog,
    *,
    provider_status: str,
    reported_duration_seconds: int | None = None,
) -> bool:
    """Record a single usage transaction for a completed call."""
    if provider_status != "completed":
        return False

    duration_seconds = resolve_call_duration_seconds(call_log, reported_duration_seconds)
    credits_to_charge = calculate_call_credits(duration_seconds)
    if credits_to_charge <= ZERO_CREDITS:
        logger.info(
            "call_billing_skipped_zero_duration",
            call_sid=call_log.call_sid,
            call_log_id=str(call_log.id),
            reported_duration_seconds=reported_duration_seconds,
        )
        return False

    existing_tx_result = await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.org_id == call_log.org_id,
            CreditTransaction.reference_id == str(call_log.id),
            CreditTransaction.type == "usage",
        )
    )
    existing_tx = existing_tx_result.scalar_one_or_none()
    if existing_tx is not None:
        logger.info(
            "call_billing_already_recorded",
            call_sid=call_log.call_sid,
            call_log_id=str(call_log.id),
            transaction_id=str(existing_tx.id),
        )
        return True

    org_result = await db.execute(
        select(Organization)
        .where(Organization.id == call_log.org_id)
        .with_for_update()
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        logger.error(
            "call_billing_org_not_found",
            call_sid=call_log.call_sid,
            org_id=str(call_log.org_id),
        )
        return False

    existing_tx_result = await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.org_id == call_log.org_id,
            CreditTransaction.reference_id == str(call_log.id),
            CreditTransaction.type == "usage",
        )
    )
    existing_tx = existing_tx_result.scalar_one_or_none()
    if existing_tx is not None:
        logger.info(
            "call_billing_already_recorded",
            call_sid=call_log.call_sid,
            call_log_id=str(call_log.id),
            transaction_id=str(existing_tx.id),
        )
        return True

    if org.credit_balance < credits_to_charge:
        logger.warning(
            "call_billing_insufficient_credits",
            call_sid=call_log.call_sid,
            org_id=str(call_log.org_id),
            balance=org.credit_balance,
            required=credits_to_charge,
        )
        return False

    new_balance = org.credit_balance - credits_to_charge
    org.credit_balance = new_balance

    tx = CreditTransaction(
        org_id=call_log.org_id,
        amount=-credits_to_charge,
        balance_after=new_balance,
        type="usage",
        description=(
            f"Call with {call_log.contact_name} - "
            f"{credits_to_charge} credit{'s' if credits_to_charge != Decimal('1.00') else ''} "
            f"for {duration_seconds}s"
        ),
        reference_id=str(call_log.id),
    )
    db.add(tx)

    metadata = dict(call_log.metadata_ or {})
    metadata["billing"] = {
        "status": "deducted",
        "credits_used": float(credits_to_charge),
        "billed_minutes": float(
            (Decimal(duration_seconds) / SECONDS_PER_MINUTE).quantize(
                CENT_PRECISION, rounding=ROUND_HALF_UP
            )
        ),
        "duration_seconds": duration_seconds,
        "balance_after": float(new_balance),
        "reference_id": str(call_log.id),
    }
    call_log.metadata_ = metadata

    await db.commit()

    logger.info(
        "call_billing_recorded",
        call_sid=call_log.call_sid,
        call_log_id=str(call_log.id),
        credits_used=credits_to_charge,
        duration_seconds=duration_seconds,
        new_balance=new_balance,
    )
    return True
