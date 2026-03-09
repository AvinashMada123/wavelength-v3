"""
Background queue processor for call gating.

Runs as an asyncio task during app lifespan. Polls call_queue for "queued"
entries, checks circuit breaker, and initiates calls using the same logic
as the webhook/API trigger endpoints.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from sqlalchemy import func, select

from app.bot_config.loader import BotConfigLoader, fill_prompt_template
from app.config import settings
from app.database import get_db_session
from app.models.call_log import CallLog
from app.models.call_queue import QueuedCall
from app.plivo.client import make_outbound_call as plivo_make_call
from app.services import circuit_breaker
from app.twilio.client import make_outbound_call as twilio_make_call

logger = structlog.get_logger(__name__)

POLL_INTERVAL = float(os.environ.get("QUEUE_POLL_INTERVAL", "3"))
MAX_CONCURRENT_PER_BOT = int(os.environ.get("QUEUE_MAX_CONCURRENT_PER_BOT", "5"))
STAGGER_DELAY_SECS = float(os.environ.get("QUEUE_STAGGER_DELAY_SECS", "2.0"))

_task: asyncio.Task | None = None
_shutdown = False
_loader: BotConfigLoader | None = None


def start(bot_config_loader: BotConfigLoader) -> asyncio.Task:
    """Start the queue processor background task."""
    global _task, _shutdown, _loader
    _shutdown = False
    _loader = bot_config_loader
    _task = asyncio.create_task(_processor_loop(bot_config_loader))
    logger.info("queue_processor_started")
    return _task


async def stop():
    """Signal the processor to stop and wait for it."""
    global _shutdown
    _shutdown = True
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    logger.info("queue_processor_stopped")


async def _processor_loop(loader: BotConfigLoader):
    """Main processing loop — polls DB for queued calls."""
    while not _shutdown:
        try:
            await _process_batch(loader)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("queue_processor_error")

        await asyncio.sleep(POLL_INTERVAL)


async def _process_batch(loader: BotConfigLoader):
    """Process one batch of queued calls across all bots.

    Calls are staggered by STAGGER_DELAY_SECS to prevent concurrent pipeline
    inits from competing for TTS connections (causes 5-6s initial silence).
    """
    async with get_db_session() as db:
        # Get distinct bot_ids that have queued calls
        result = await db.execute(
            select(QueuedCall.bot_id)
            .where(QueuedCall.status == "queued")
            .distinct()
        )
        bot_ids = [row[0] for row in result.all()]

    # Collect all calls to process, then stagger initiation across all bots
    calls_to_process: list[tuple] = []  # (queue_id, bot_id)

    for bot_id in bot_ids:
        async with get_db_session() as db:
            # Check circuit breaker
            if await circuit_breaker.is_open(db, bot_id):
                continue

            # Check how many are currently processing for this bot
            result = await db.execute(
                select(func.count()).select_from(QueuedCall).where(
                    QueuedCall.bot_id == bot_id,
                    QueuedCall.status == "processing",
                )
            )
            active = result.scalar() or 0

            slots_available = MAX_CONCURRENT_PER_BOT - active
            if slots_available <= 0:
                continue

            # Fetch next batch of queued calls for this bot
            result = await db.execute(
                select(QueuedCall)
                .where(QueuedCall.bot_id == bot_id, QueuedCall.status == "queued")
                .order_by(QueuedCall.priority.desc(), QueuedCall.created_at.asc())
                .limit(slots_available)
            )
            calls = result.scalars().all()

            for queued_call in calls:
                queued_call.status = "processing"
                calls_to_process.append((queued_call.id, queued_call.bot_id))
            await db.commit()

    # Stagger call initiation to avoid concurrent pipeline/TTS contention
    for i, (queue_id, bot_id) in enumerate(calls_to_process):
        if i > 0 and STAGGER_DELAY_SECS > 0:
            await asyncio.sleep(STAGGER_DELAY_SECS)
        asyncio.create_task(_process_single_call(loader, queue_id, bot_id))

    if len(calls_to_process) > 1:
        logger.info(
            "batch_staggered",
            total=len(calls_to_process),
            stagger_secs=STAGGER_DELAY_SECS,
        )


async def _process_single_call(loader: BotConfigLoader, queue_id, bot_id):
    """Process a single queued call — same logic as webhook trigger."""
    async with get_db_session() as db:
        result = await db.execute(
            select(QueuedCall).where(QueuedCall.id == queue_id)
        )
        queued_call = result.scalar_one_or_none()
        if not queued_call or queued_call.status != "processing":
            return

        try:
            # Load bot config
            bot_config = await loader.get(str(bot_id))
            if not bot_config:
                queued_call.status = "failed"
                queued_call.error_message = "Bot config not found or inactive"
                queued_call.processed_at = datetime.now(timezone.utc)
                await db.commit()
                await circuit_breaker.record_failure(db, bot_id, "Bot config not found")
                await db.commit()
                return

            # Fill prompt template
            ctx_vars = bot_config.context_variables or {}
            template_vars = ctx_vars if isinstance(ctx_vars, dict) else {}
            template_vars.update(
                contact_name=queued_call.contact_name,
                agent_name=bot_config.agent_name,
                company_name=bot_config.company_name,
                location=bot_config.location or "",
                event_name=bot_config.event_name or "",
                event_date=bot_config.event_date or "",
                event_time=bot_config.event_time or "",
            )
            template_vars.update(queued_call.extra_vars or {})

            filled_prompt = fill_prompt_template(
                bot_config.system_prompt_template, **template_vars
            )

            # Create call log
            call_sid = str(uuid4())
            call_log = CallLog(
                bot_id=bot_config.id,
                call_sid=call_sid,
                contact_name=queued_call.contact_name,
                contact_phone=queued_call.contact_phone,
                ghl_contact_id=queued_call.ghl_contact_id,
                status="initiated",
                context_data={
                    "bot_id": str(bot_config.id),
                    "filled_prompt": filled_prompt,
                    "contact_name": queued_call.contact_name,
                    "ghl_contact_id": queued_call.ghl_contact_id,
                    "ghl_webhook_url": bot_config.ghl_webhook_url,
                    "tts_provider": bot_config.tts_provider,
                    "tts_voice": bot_config.tts_voice,
                    "tts_style_prompt": bot_config.tts_style_prompt,
                    "language": bot_config.language,
                    "silence_timeout_secs": bot_config.silence_timeout_secs,
                },
            )
            db.add(call_log)
            await db.flush()

            # Initiate outbound call
            provider = getattr(bot_config, "telephony_provider", "plivo") or "plivo"
            base_url = settings.PUBLIC_BASE_URL

            if provider == "twilio":
                provider_uuid = await twilio_make_call(
                    account_sid=bot_config.twilio_account_sid,
                    auth_token=bot_config.twilio_auth_token,
                    from_number=bot_config.twilio_phone_number,
                    to_number=queued_call.contact_phone,
                    answer_url=f"{base_url}/twilio/answer/{call_sid}",
                    status_callback_url=f"{base_url}/twilio/event/{call_sid}",
                )
            else:
                provider_uuid = await plivo_make_call(
                    auth_id=bot_config.plivo_auth_id,
                    auth_token=bot_config.plivo_auth_token,
                    from_number=bot_config.plivo_caller_id,
                    to_number=queued_call.contact_phone,
                    answer_url=f"{base_url}/plivo/answer/{call_sid}",
                    hangup_url=f"{base_url}/plivo/event/{call_sid}",
                )

            if not provider_uuid:
                # Provider call failed — system failure
                call_log.status = "failed"
                queued_call.status = "failed"
                queued_call.error_message = f"{provider} call initiation failed"
                queued_call.processed_at = datetime.now(timezone.utc)
                await db.commit()

                tripped = await circuit_breaker.record_failure(
                    db, bot_id, f"{provider} call initiation failed"
                )
                await db.commit()
                if tripped:
                    logger.warning("circuit_breaker_tripped_from_queue", bot_id=str(bot_id))
                return

            # Success
            call_log.plivo_call_uuid = provider_uuid
            call_log.status = "ringing"
            queued_call.status = "completed"
            queued_call.call_log_id = call_log.id
            queued_call.processed_at = datetime.now(timezone.utc)
            await db.commit()

            await circuit_breaker.record_success(db, bot_id)
            await db.commit()

            logger.info(
                "queue_call_processed",
                queue_id=str(queue_id),
                call_sid=call_sid,
                provider=provider,
                to=queued_call.contact_phone,
            )

        except Exception as e:
            logger.exception("queue_call_processing_error", queue_id=str(queue_id))
            queued_call.status = "failed"
            queued_call.error_message = str(e)[:500]
            queued_call.processed_at = datetime.now(timezone.utc)
            await db.commit()

            tripped = await circuit_breaker.record_failure(db, bot_id, str(e)[:200])
            await db.commit()
