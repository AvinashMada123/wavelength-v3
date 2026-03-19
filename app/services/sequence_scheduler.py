"""Background scheduler that polls for due touchpoints and fires them."""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_

from app.database import get_db_session
from app.models.sequence import SequenceTouchpoint, SequenceInstance
from app.services import sequence_engine

logger = structlog.get_logger(__name__)

POLL_INTERVAL = 10  # seconds
MAX_CONCURRENT = 10  # max touchpoints processed in parallel per batch

_shutdown = False
_task: asyncio.Task | None = None


def start():
    """Start the sequence scheduler background task."""
    global _task, _shutdown
    _shutdown = False
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("sequence_scheduler_started", poll_interval=POLL_INTERVAL)


async def stop():
    """Stop the scheduler gracefully."""
    global _shutdown, _task
    _shutdown = True
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    logger.info("sequence_scheduler_stopped")


async def _scheduler_loop():
    """Main loop — polls DB for due touchpoints."""
    cycle_count = 0
    while not _shutdown:
        try:
            await _process_batch()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sequence_scheduler_error")

        # Every 5th cycle, retry failed touchpoints that haven't hit max retries
        cycle_count += 1
        if cycle_count % 5 == 0:
            try:
                await _retry_failed()
            except Exception:
                logger.exception("sequence_retry_failed_error")

        await asyncio.sleep(POLL_INTERVAL)


async def _process_batch():
    """Find and process all due touchpoints."""
    now = datetime.utcnow()

    async with get_db_session() as db:
        # Find due touchpoints: pending/scheduled and scheduled_at in the past
        # Skip touchpoints belonging to paused/cancelled instances
        result = await db.execute(
            select(SequenceTouchpoint)
            .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
            .where(
                SequenceTouchpoint.status.in_(["pending", "scheduled"]),
                SequenceTouchpoint.scheduled_at <= now,
                SequenceInstance.status == "active",
            )
            .order_by(SequenceTouchpoint.scheduled_at.asc())
            .limit(MAX_CONCURRENT * 2)  # Fetch more than we process to account for skips
            .with_for_update(skip_locked=True)
        )
        touchpoints = result.scalars().all()

        # Phone spacing: skip touchpoints whose lead had a message sent <60s ago
        # This prevents WhatsApp rate limiting when multiple sequences target same lead
        _recent_phones: dict[str, datetime] = {}
        filtered = []
        for tp in touchpoints:
            # Get phone from instance context (cheap: already in memory after join)
            phone = None
            if tp.step_snapshot and tp.step_snapshot.get("channel", "").startswith("whatsapp"):
                inst_result = await db.execute(
                    select(SequenceInstance.context_data).where(SequenceInstance.id == tp.instance_id)
                )
                ctx = inst_result.scalar_one_or_none() or {}
                phone = ctx.get("contact_phone", "")[-10:] if isinstance(ctx, dict) else ""

            if phone and phone in _recent_phones:
                last_sent = _recent_phones[phone]
                if (now - last_sent).total_seconds() < 60:
                    continue  # Skip — too soon for this phone

            filtered.append(tp)
            if phone:
                _recent_phones[phone] = now

        touchpoints = filtered

        if not touchpoints:
            return

        logger.info("sequence_scheduler_batch", count=len(touchpoints))

        # Process in bounded parallel batches
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _process_one(tp_id):
            async with semaphore:
                # Each touchpoint gets its own DB session for isolation
                async with get_db_session() as tp_db:
                    tp_result = await tp_db.execute(
                        select(SequenceTouchpoint)
                        .where(SequenceTouchpoint.id == tp_id)
                        .with_for_update(skip_locked=True)
                    )
                    tp = tp_result.scalar_one_or_none()
                    if not tp or tp.status != "pending":
                        return

                    try:
                        await sequence_engine.process_touchpoint(tp_db, tp)
                    except Exception:
                        logger.exception("sequence_touchpoint_processing_failed", touchpoint_id=str(tp_id))
                        tp.status = "failed"
                        tp.error_message = "Unexpected processing error"
                        tp.retry_count += 1
                        await tp_db.commit()

        # Launch all in parallel (bounded by semaphore)
        tasks = [asyncio.create_task(_process_one(tp.id)) for tp in touchpoints]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Release the original FOR UPDATE lock
        await db.commit()


async def _retry_failed():
    """Re-queue failed touchpoints that haven't hit max retries."""
    async with get_db_session() as db:
        result = await db.execute(
            select(SequenceTouchpoint).where(
                SequenceTouchpoint.status == "failed",
                SequenceTouchpoint.retry_count < SequenceTouchpoint.max_retries,
            )
        )
        retryable = result.scalars().all()
        for tp in retryable:
            tp.status = "pending"
            logger.info("sequence_touchpoint_retry", touchpoint_id=str(tp.id), retry=tp.retry_count)
        if retryable:
            await db.commit()
