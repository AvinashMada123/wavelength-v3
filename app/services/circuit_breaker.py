"""
Per-bot circuit breaker for call queue gating.

States:
- closed: Normal operation, calls flow through.
- open: Calls are held, no new calls processed for this bot.
- half_open: Not used yet (manual reset required).

Only system failures trip the breaker (provider errors, pipeline crashes).
Normal call outcomes (no_answer, busy, voicemail) do NOT count as failures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_queue import CircuitBreakerState, QueuedCall

logger = structlog.get_logger(__name__)

# Statuses that indicate a system failure (not a normal call outcome)
SYSTEM_FAILURE_STATUSES = {"failed", "error"}


async def get_or_create(db: AsyncSession, bot_id) -> CircuitBreakerState:
    """Get circuit breaker state for a bot, creating default if not exists."""
    result = await db.execute(
        select(CircuitBreakerState).where(CircuitBreakerState.bot_id == bot_id)
    )
    cb = result.scalar_one_or_none()
    if cb is None:
        cb = CircuitBreakerState(bot_id=bot_id)
        db.add(cb)
        await db.flush()
    return cb


async def is_open(db: AsyncSession, bot_id) -> bool:
    """Check if circuit breaker is open (calls should be held)."""
    cb = await get_or_create(db, bot_id)
    return cb.state == "open"


async def record_success(db: AsyncSession, bot_id) -> None:
    """Record a successful call — resets consecutive failure counter."""
    cb = await get_or_create(db, bot_id)
    if cb.consecutive_failures > 0:
        cb.consecutive_failures = 0
        cb.updated_at = datetime.now(timezone.utc)
        logger.info("circuit_breaker_success_reset", bot_id=str(bot_id))


async def record_failure(db: AsyncSession, bot_id, reason: str) -> bool:
    """
    Record a system failure. Returns True if circuit just tripped open.
    """
    cb = await get_or_create(db, bot_id)
    cb.consecutive_failures += 1
    cb.last_failure_at = datetime.now(timezone.utc)
    cb.last_failure_reason = reason
    cb.updated_at = datetime.now(timezone.utc)

    tripped = False
    if cb.state == "closed" and cb.consecutive_failures >= cb.failure_threshold:
        cb.state = "open"
        cb.opened_at = datetime.now(timezone.utc)
        cb.opened_by = "auto"
        tripped = True

        # Mark all queued calls for this bot as "held"
        await _hold_queued_calls(db, bot_id, reason)

        logger.warning(
            "circuit_breaker_tripped",
            bot_id=str(bot_id),
            failures=cb.consecutive_failures,
            threshold=cb.failure_threshold,
            reason=reason,
        )

    return tripped


async def manual_open(db: AsyncSession, bot_id, reason: str = "Manual pause") -> None:
    """Manually open the circuit breaker (pause calls)."""
    cb = await get_or_create(db, bot_id)
    cb.state = "open"
    cb.opened_at = datetime.now(timezone.utc)
    cb.opened_by = "manual"
    cb.last_failure_reason = reason
    cb.updated_at = datetime.now(timezone.utc)

    await _hold_queued_calls(db, bot_id, reason)
    logger.info("circuit_breaker_manual_open", bot_id=str(bot_id))


async def reset(db: AsyncSession, bot_id) -> None:
    """Close the circuit breaker and release held calls back to queued."""
    cb = await get_or_create(db, bot_id)
    cb.state = "closed"
    cb.consecutive_failures = 0
    cb.opened_at = None
    cb.opened_by = None
    cb.updated_at = datetime.now(timezone.utc)

    # Release held calls back to queued
    await _release_held_calls(db, bot_id)
    logger.info("circuit_breaker_reset", bot_id=str(bot_id))


async def update_threshold(db: AsyncSession, bot_id, threshold: int) -> None:
    """Update the failure threshold for a bot's circuit breaker."""
    cb = await get_or_create(db, bot_id)
    cb.failure_threshold = max(1, threshold)
    cb.updated_at = datetime.now(timezone.utc)


async def _hold_queued_calls(db: AsyncSession, bot_id, reason: str) -> None:
    """Mark all queued calls for a bot as held."""
    result = await db.execute(
        select(QueuedCall).where(
            QueuedCall.bot_id == bot_id,
            QueuedCall.status == "queued",
        )
    )
    for call in result.scalars().all():
        call.status = "held"
        call.error_message = f"Circuit breaker tripped: {reason}"


async def _release_held_calls(db: AsyncSession, bot_id) -> None:
    """Release held calls back to queued status."""
    result = await db.execute(
        select(QueuedCall).where(
            QueuedCall.bot_id == bot_id,
            QueuedCall.status == "held",
        )
    )
    for call in result.scalars().all():
        call.status = "queued"
        call.error_message = None
