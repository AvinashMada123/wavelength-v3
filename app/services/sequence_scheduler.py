"""Background scheduler that polls for due touchpoints and fires them."""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_

from app.database import get_db_session
from app.models.organization import Organization
from app.models.sequence import SequenceTouchpoint, SequenceInstance
from app.services import sequence_engine
from app.services.business_hours import is_within_business_hours, next_available_time
from app.services.rate_limiter import RateLimiter

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

        # Persistent rate limiting: skip touchpoints whose lead has been contacted
        # too recently. Replaces the old in-memory _recent_phones dict.
        limiter = RateLimiter(db=db)
        filtered = []
        for tp in touchpoints:
            if tp.lead_id and tp.org_id:
                if not await limiter.can_contact(lead_id=str(tp.lead_id), org_id=str(tp.org_id)):
                    logger.debug("rate_limit_skip", touchpoint_id=str(tp.id), lead_id=str(tp.lead_id))
                    continue
            filtered.append(tp)

        touchpoints = filtered

        # Business hours check: defer touchpoints outside org's configured window
        now_aware = datetime.now(timezone.utc)
        org_hours_cache: dict[str, dict] = {}  # org_id -> business_hours config
        ready = []
        for tp in touchpoints:
            org_key = str(tp.org_id) if tp.org_id else None
            if org_key:
                if org_key not in org_hours_cache:
                    org_result = await db.execute(
                        select(Organization).where(Organization.id == tp.org_id)
                    )
                    org = org_result.scalar_one_or_none()
                    org_hours_cache[org_key] = (
                        org.settings.get("business_hours", {}) if org and org.settings else {}
                    )
                bh_config = org_hours_cache[org_key]
                if not is_within_business_hours(now_aware, bh_config):
                    # Reschedule to next available window instead of silently skipping
                    next_time = next_available_time(now_aware, bh_config)
                    tp.scheduled_at = next_time
                    logger.debug(
                        "business_hours_defer",
                        touchpoint_id=str(tp.id),
                        next_time=next_time.isoformat(),
                    )
                    continue
            ready.append(tp)
        touchpoints = ready

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
                        # Record contact for rate limiting after successful send
                        if tp.lead_id and tp.org_id:
                            rl = RateLimiter(db=tp_db)
                            await rl.record_contact(
                                lead_id=str(tp.lead_id),
                                org_id=str(tp.org_id),
                                channel=tp.step_snapshot.get("channel", "unknown") if tp.step_snapshot else "unknown",
                            )
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
