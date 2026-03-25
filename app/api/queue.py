"""Queue & circuit breaker management API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_org
from app.database import get_db
from app.models.bot_config import BotConfig
from app.models.call_queue import CircuitBreakerState, QueuedCall
from app.models.schemas import (
    CircuitBreakerResponse,
    QueuedCallResponse,
    QueueStatsResponse,
)
from app.services import circuit_breaker

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/queue", tags=["queue"])


class EnqueueCallRequest(BaseModel):
    bot_id: uuid.UUID
    contact_name: str
    contact_phone: str


# ---- Queue endpoints ----


@router.get("", response_model=list[QueuedCallResponse])
async def list_queued_calls(
    bot_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """List calls in the queue with optional filters."""
    query = (
        select(QueuedCall, BotConfig.agent_name)
        .join(BotConfig, QueuedCall.bot_id == BotConfig.id, isouter=True)
        .where(QueuedCall.org_id == org_id)
        .order_by(QueuedCall.created_at.desc())
    )
    if bot_id:
        query = query.where(QueuedCall.bot_id == bot_id)
    if status:
        query = query.where(QueuedCall.status == status)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [
        QueuedCallResponse(
            **{c.key: getattr(row[0], c.key) for c in QueuedCall.__table__.columns},
            bot_name=row[1],
        )
        for row in rows
    ]


@router.get("/stats", response_model=list[QueueStatsResponse])
async def queue_stats(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Get queue counts grouped by bot and status."""
    query = (
        select(
            QueuedCall.bot_id,
            BotConfig.agent_name.label("bot_name"),
            QueuedCall.status,
            func.count().label("count"),
        )
        .join(BotConfig, QueuedCall.bot_id == BotConfig.id, isouter=True)
        .where(QueuedCall.org_id == org_id)
        .group_by(QueuedCall.bot_id, BotConfig.agent_name, QueuedCall.status)
    )
    result = await db.execute(query)
    rows = result.all()

    # Pivot into per-bot stats
    stats_map: dict[uuid.UUID, QueueStatsResponse] = {}
    for bot_id, bot_name, status, count in rows:
        if bot_id not in stats_map:
            stats_map[bot_id] = QueueStatsResponse(
                bot_id=bot_id, bot_name=bot_name or "Unknown"
            )
        s = stats_map[bot_id]
        if status in ("queued", "held", "processing", "completed", "failed", "cancelled"):
            setattr(s, status, count)
    return list(stats_map.values())


@router.post("/{queue_id}/cancel")
async def cancel_queued_call(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Cancel a single queued/held call."""
    result = await db.execute(select(QueuedCall).where(QueuedCall.id == queue_id, QueuedCall.org_id == org_id))
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    if call.status not in ("queued", "held"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel call in '{call.status}' status")
    call.status = "cancelled"
    call.processed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "cancelled", "queue_id": str(queue_id)}


@router.post("/{queue_id}/trigger")
async def trigger_queued_call(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Force-trigger a single queued/held call, bypassing circuit breaker.

    Useful for testing individual calls when the bot is paused.
    """
    result = await db.execute(select(QueuedCall).where(QueuedCall.id == queue_id, QueuedCall.org_id == org_id))
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    if call.status not in ("queued", "held"):
        raise HTTPException(status_code=400, detail=f"Cannot trigger call in '{call.status}' status")

    call.status = "processing"
    call.source = "manual"  # Mark as manual so it bypasses calling window
    await db.commit()

    # Fire-and-forget: process this call in the background
    import asyncio
    from app.services.queue_processor import _process_single_call, _loader

    if not _loader:
        raise HTTPException(status_code=503, detail="Queue processor not initialized")

    asyncio.create_task(_process_single_call(_loader, call.id, call.bot_id))
    logger.info("queue_call_manually_triggered", queue_id=str(queue_id), contact=call.contact_name)
    return {"status": "triggered", "queue_id": str(queue_id)}


@router.post("/enqueue")
async def enqueue_call(
    body: EnqueueCallRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Enqueue a single call for a bot."""
    # Validate bot belongs to org
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == body.bot_id, BotConfig.org_id == org_id)
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    call = QueuedCall(
        org_id=org_id,
        bot_id=body.bot_id,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        source="api",
        status="queued",
        priority=0,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    logger.info("call_enqueued_manual", queue_id=str(call.id), contact=body.contact_name)
    return {"status": "queued", "queue_id": str(call.id)}


@router.post("/bulk-cancel")
async def bulk_cancel(
    queue_ids: list[uuid.UUID],
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Cancel multiple queued/held calls."""
    result = await db.execute(
        select(QueuedCall).where(
            QueuedCall.id.in_(queue_ids),
            QueuedCall.org_id == org_id,
            QueuedCall.status.in_(["queued", "held"]),
        )
    )
    calls = result.scalars().all()
    now = datetime.now(timezone.utc)
    for call in calls:
        call.status = "cancelled"
        call.processed_at = now
    await db.commit()
    return {"cancelled": len(calls)}


@router.post("/bulk-approve")
async def bulk_approve(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Approve all held calls for a bot — resets circuit breaker and releases calls."""
    # Verify the bot belongs to the user's org
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id)
    )
    if not bot_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bot config not found")
    await circuit_breaker.reset(db, bot_id)
    await db.commit()
    return {"status": "approved", "bot_id": str(bot_id)}


# ---- Circuit Breaker endpoints ----


@router.get("/circuit-breaker", response_model=list[CircuitBreakerResponse])
async def list_circuit_breakers(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """List circuit breaker state for all bots."""
    result = await db.execute(
        select(CircuitBreakerState, BotConfig.agent_name)
        .join(BotConfig, CircuitBreakerState.bot_id == BotConfig.id, isouter=True)
        .where(BotConfig.org_id == org_id)
    )
    rows = result.all()
    return [
        CircuitBreakerResponse(
            **{c.key: getattr(row[0], c.key) for c in CircuitBreakerState.__table__.columns},
            bot_name=row[1],
        )
        for row in rows
    ]


@router.get("/circuit-breaker/{bot_id}", response_model=CircuitBreakerResponse)
async def get_circuit_breaker(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Get circuit breaker state for a specific bot."""
    # Verify the bot belongs to the user's org
    bot_result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    if not bot_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bot config not found")
    cb = await circuit_breaker.get_or_create(db, bot_id)
    await db.commit()
    result = await db.execute(select(BotConfig.agent_name).where(BotConfig.id == bot_id))
    bot_name = result.scalar_one_or_none()
    return CircuitBreakerResponse(
        **{c.key: getattr(cb, c.key) for c in CircuitBreakerState.__table__.columns},
        bot_name=bot_name,
    )


@router.post("/circuit-breaker/{bot_id}/open")
async def open_circuit_breaker(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Manually pause calls for a bot."""
    # Verify the bot belongs to the user's org
    bot_result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    if not bot_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bot config not found")
    await circuit_breaker.manual_open(db, bot_id)
    await db.commit()
    return {"status": "open", "bot_id": str(bot_id)}


@router.post("/circuit-breaker/{bot_id}/reset")
async def reset_circuit_breaker(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Reset circuit breaker — resumes call processing and releases held calls."""
    # Verify the bot belongs to the user's org
    bot_result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    if not bot_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bot config not found")
    await circuit_breaker.reset(db, bot_id)
    await db.commit()
    return {"status": "closed", "bot_id": str(bot_id)}


@router.patch("/circuit-breaker/{bot_id}/settings")
async def update_circuit_breaker_settings(
    bot_id: uuid.UUID,
    failure_threshold: int = Query(ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Update circuit breaker threshold for a bot."""
    # Verify the bot belongs to the user's org
    bot_result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    if not bot_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bot config not found")
    await circuit_breaker.update_threshold(db, bot_id, failure_threshold)
    await db.commit()
    return {"status": "updated", "failure_threshold": failure_threshold}
