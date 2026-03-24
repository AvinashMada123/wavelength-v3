"""
Background queue processor for call gating.

Runs as an asyncio task during app lifespan. Polls call_queue for "queued"
entries, checks circuit breaker, and initiates calls using the same logic
as the webhook/API trigger endpoints.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select, update

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_config.loader import BotConfigLoader, fill_prompt_template
from app.services.call_memory import build_call_memory_prompt
from app.services.lead_sync import find_or_create_lead
from app.config import settings
from app.database import get_db_session
from app.models.call_log import CallLog
from app.models.call_queue import QueuedCall
from app.models.campaign import Campaign, CampaignLead
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.phone_number import PhoneNumber
from app.plivo.client import make_outbound_call as plivo_make_call
from app.services import circuit_breaker
from app.services.billing import check_org_credits
from app.twilio.client import make_outbound_call as twilio_make_call
from app.utils import normalize_phone_india

logger = structlog.get_logger(__name__)

POLL_INTERVAL = float(os.environ.get("QUEUE_POLL_INTERVAL", "3"))
MAX_CONCURRENT_PER_BOT = int(os.environ.get("QUEUE_MAX_CONCURRENT_PER_BOT", "5"))
STAGGER_DELAY_SECS = float(os.environ.get("QUEUE_STAGGER_DELAY_SECS", "2.0"))
# Calls stuck in "ringing" or "initiated" longer than this are marked stale
STALE_CALL_TIMEOUT_MINS = int(os.environ.get("STALE_CALL_TIMEOUT_MINS", "5"))

_task: asyncio.Task | None = None
_shutdown = False
_loader: BotConfigLoader | None = None


async def _resolve_telephony(
    db: AsyncSession, bot_config
) -> tuple[str, str, dict[str, str]]:
    """Resolve telephony provider, phone number, and auth credentials.

    Prefers org-level credentials + phone_numbers table.
    Falls back to bot-level credentials for backward compatibility.

    Returns: (provider, from_number, auth_creds_dict)
    """
    org_id = bot_config.org_id

    # Check if bot has a specific phone_number_id assigned
    phone_number_id = getattr(bot_config, "phone_number_id", None)

    if phone_number_id:
        pn_result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == phone_number_id)
        )
        phone = pn_result.scalar_one_or_none()
        if phone:
            provider = phone.provider
            from_number = phone.phone_number
        else:
            # Phone number was deleted — fall back to default
            phone_number_id = None

    if not phone_number_id:
        # Use the default phone number for the bot's telephony provider
        provider = getattr(bot_config, "telephony_provider", "plivo") or "plivo"
        pn_result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.org_id == org_id,
                PhoneNumber.provider == provider,
                PhoneNumber.is_default == True,
            ).limit(1)
        )
        phone = pn_result.scalars().first()
        if phone:
            from_number = phone.phone_number
        else:
            # Final fallback to bot-level caller ID
            if provider == "twilio":
                from_number = getattr(bot_config, "twilio_phone_number", "") or ""
            else:
                from_number = getattr(bot_config, "plivo_caller_id", "") or ""

    # Resolve auth credentials — org-level first, bot-level fallback
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()

    if provider == "twilio":
        auth_creds = {
            "account_sid": (org.twilio_account_sid if org and org.twilio_account_sid else None)
                or getattr(bot_config, "twilio_account_sid", "") or "",
            "auth_token": (org.twilio_auth_token if org and org.twilio_auth_token else None)
                or getattr(bot_config, "twilio_auth_token", "") or "",
        }
    else:
        auth_creds = {
            "auth_id": (org.plivo_auth_id if org and org.plivo_auth_id else None)
                or getattr(bot_config, "plivo_auth_id", "") or "",
            "auth_token": (org.plivo_auth_token if org and org.plivo_auth_token else None)
                or getattr(bot_config, "plivo_auth_token", "") or "",
        }

    return provider, from_number, auth_creds


def _normalize_template_vars(template_vars: dict[str, str]) -> dict[str, str]:
    """Normalize common external variable aliases into prompt placeholder names."""
    normalized = dict(template_vars)

    alias_map = {
        "event_host": (
            "event_hostname",
            "eventHostName",
            "eventHost",
            "hostname",
            "hostName",
            "host_name",
        ),
        "customer_profession": (
            "profession",
            "customerProfession",
            "customer_profession",
            "customerProfessionName",
        ),
        "customer_name": ("name", "contact_name", "contactName", "customerName"),
    }

    def canonical(key: str) -> str:
        return "".join(ch for ch in key.lower() if ch.isalnum())

    present_by_canonical = {
        canonical(str(key)): value
        for key, value in normalized.items()
        if value not in (None, "")
    }

    for target_key, aliases in alias_map.items():
        if normalized.get(target_key):
            continue
        for alias in aliases:
            value = normalized.get(alias)
            if not value:
                value = present_by_canonical.get(canonical(alias))
            if value:
                normalized[target_key] = value
                break

    return normalized


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


async def _cleanup_stale_calls():
    """Mark calls stuck in 'ringing' or 'initiated' as 'no_answer' after timeout.
    Also reset queue entries stuck in 'processing' for too long (e.g. Plivo callback
    never arrived, pipeline crashed) so they don't block concurrency slots forever.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_CALL_TIMEOUT_MINS)
    async with get_db_session() as db:
        result = await db.execute(
            update(CallLog)
            .where(
                CallLog.status.in_(["ringing", "initiated"]),
                CallLog.created_at < cutoff,
            )
            .values(
                status="no_answer",
                ended_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount > 0:
            logger.info("stale_calls_cleaned", count=result.rowcount)

        # Reset queue entries stuck in 'processing' for more than 10 minutes.
        # processed_at is set when entering 'processing'; fall back to created_at
        # for legacy rows that were never stamped.
        queue_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        queue_result = await db.execute(
            update(QueuedCall)
            .where(
                QueuedCall.status == "processing",
                func.coalesce(QueuedCall.processed_at, QueuedCall.created_at) < queue_cutoff,
            )
            .values(status="failed", error_message="Stale processing — auto-reset")
            .returning(QueuedCall.id)
        )
        stale_queue_ids = queue_result.scalars().all()
        if stale_queue_ids:
            logger.warning(
                "stale_processing_queue_reset",
                count=len(stale_queue_ids),
                ids=[str(qid) for qid in stale_queue_ids],
            )

        await db.commit()


async def _processor_loop(loader: BotConfigLoader):
    """Main processing loop — polls DB for queued calls."""
    cleanup_counter = 0
    while not _shutdown:
        try:
            await _process_batch(loader)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("queue_processor_error")

        # Run stale call cleanup every ~30s (every 10 poll cycles)
        cleanup_counter += 1
        if cleanup_counter >= 10:
            cleanup_counter = 0
            try:
                await _cleanup_stale_calls()
            except Exception:
                logger.exception("stale_call_cleanup_error")

        await asyncio.sleep(POLL_INTERVAL)


async def _get_org_max_concurrent(db: AsyncSession, org_id) -> int:
    """Read max_concurrent_calls from org settings, default 15."""
    result = await db.execute(
        select(Organization.settings).where(Organization.id == org_id)
    )
    settings = result.scalar_one_or_none() or {}
    return int(settings.get("max_concurrent_calls", 15))


async def _process_batch(loader: BotConfigLoader):
    """Process one batch of queued calls across all bots.

    Calls are staggered by STAGGER_DELAY_SECS to prevent concurrent pipeline
    inits from competing for TTS connections (causes 5-6s initial silence).
    """
    async with get_db_session() as db:
        # Get distinct bot_ids that have queued calls, along with their org_id
        result = await db.execute(
            select(QueuedCall.bot_id, QueuedCall.org_id)
            .where(QueuedCall.status == "queued")
            .distinct()
        )
        bot_rows = result.all()
        bot_ids = [row[0] for row in bot_rows]

    # Build org_id lookup and track org-level concurrency
    bot_org_map: dict = {}
    org_active_counts: dict = {}
    org_limits: dict = {}

    for bot_id, org_id in bot_rows:
        bot_org_map[bot_id] = org_id

    # Pre-fetch org limits and active counts
    for org_id in set(bot_org_map.values()):
        async with get_db_session() as db:
            org_limits[org_id] = await _get_org_max_concurrent(db, org_id)
            result = await db.execute(
                select(func.count()).select_from(QueuedCall).where(
                    QueuedCall.org_id == org_id,
                    QueuedCall.status == "processing",
                )
            )
            org_active_counts[org_id] = result.scalar() or 0

    # Collect all calls to process, then stagger initiation across all bots
    calls_to_process: list[tuple] = []  # (queue_id, bot_id)

    for bot_id in bot_ids:
        org_id = bot_org_map.get(bot_id)

        # Check org-level concurrency limit
        if org_id and org_active_counts.get(org_id, 0) >= org_limits.get(org_id, 15):
            continue

        async with get_db_session() as db:
            # Check circuit breaker
            if await circuit_breaker.is_open(db, bot_id):
                continue

            # Check how many calls are actively running pipelines for this bot
            # Count both queue "processing" AND call_logs "in_progress" to catch
            # calls that connected but are still on a WebSocket pipeline
            result = await db.execute(
                select(func.count()).select_from(CallLog).where(
                    CallLog.bot_id == bot_id,
                    CallLog.status.in_(["initiated", "ringing", "in_progress"]),
                )
            )
            active = result.scalar() or 0

            # Use per-bot concurrency limit from config, fallback to global env var
            bot_config = await loader.get(str(bot_id))
            bot_max = getattr(bot_config, "max_concurrent_calls", MAX_CONCURRENT_PER_BOT) if bot_config else MAX_CONCURRENT_PER_BOT

            slots_available = bot_max - active
            if slots_available <= 0:
                continue

            # Also cap by org-level remaining slots
            if org_id:
                org_remaining = org_limits.get(org_id, 15) - org_active_counts.get(org_id, 0)
                slots_available = min(slots_available, org_remaining)
                if slots_available <= 0:
                    continue

            # Fetch next batch of queued calls for this bot
            # FOR UPDATE SKIP LOCKED prevents multiple workers from picking up the same call
            # Filter out future-scheduled calls (scheduled_at in the future)
            from sqlalchemy import or_

            now_utc = datetime.now(timezone.utc)
            result = await db.execute(
                select(QueuedCall)
                .where(
                    QueuedCall.bot_id == bot_id,
                    QueuedCall.status == "queued",
                    or_(
                        QueuedCall.scheduled_at.is_(None),
                        QueuedCall.scheduled_at <= now_utc,
                    ),
                )
                .order_by(QueuedCall.priority.desc(), QueuedCall.created_at.asc())
                .limit(slots_available)
                .with_for_update(skip_locked=True)
            )
            calls = result.scalars().all()

            for queued_call in calls:
                queued_call.status = "processing"
                queued_call.processed_at = datetime.now(timezone.utc)
                calls_to_process.append((queued_call.id, queued_call.bot_id))
                # Track org-level count
                if org_id:
                    org_active_counts[org_id] = org_active_counts.get(org_id, 0) + 1
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
                if queued_call.campaign_id and queued_call.campaign_lead_id:
                    await _handle_campaign_call_result(
                        db, queued_call.campaign_id, queued_call.campaign_lead_id,
                        call_log_id=None, success=False,
                    )
                return

            # Enforce callback retry limit and calling window for scheduled calls
            if queued_call.scheduled_at is not None:
                max_retries = getattr(bot_config, "callback_max_retries", 3)
                if queued_call.retry_count > max_retries:
                    queued_call.status = "failed"
                    queued_call.error_message = f"Max callback retries ({max_retries}) exceeded"
                    queued_call.processed_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(
                        "callback_max_retries_exceeded",
                        queue_id=str(queue_id),
                        retry_count=queued_call.retry_count,
                    )
                    return

                # Check calling window
                tz_name = getattr(bot_config, "callback_timezone", "Asia/Kolkata")
                window_start = getattr(bot_config, "callback_window_start", 9)
                window_end = getattr(bot_config, "callback_window_end", 20)
                try:
                    from zoneinfo import ZoneInfo
                    tz = ZoneInfo(tz_name)
                    local_now = datetime.now(tz)
                    if not (window_start <= local_now.hour < window_end):
                        # Outside calling window — keep as queued, will be picked up later
                        logger.info(
                            "callback_outside_window",
                            queue_id=str(queue_id),
                            local_hour=local_now.hour,
                            window=f"{window_start}-{window_end}",
                        )
                        return
                except Exception as e:
                    logger.error("callback_window_check_failed", error=str(e))
                    # Proceed anyway on timezone errors

            # Check org has enough credits before dialing
            has_credits, balance = await check_org_credits(db, bot_config.org_id)
            if not has_credits:
                logger.warning(
                    "queue_call_insufficient_credits",
                    queue_id=str(queue_id),
                    bot_id=str(bot_id),
                    org_id=str(bot_config.org_id),
                    balance=float(balance),
                )
                queued_call.status = "failed"
                queued_call.error_message = "Insufficient credits"
                queued_call.processed_at = datetime.now(timezone.utc)
                await db.commit()
                if queued_call.campaign_id and queued_call.campaign_lead_id:
                    await _handle_campaign_call_result(
                        db, queued_call.campaign_id, queued_call.campaign_lead_id,
                        call_log_id=None, success=False,
                    )
                return

            # Auto-create or find lead for this contact (before prompt fill
            # so saved lead vars are available as fallbacks)
            lead_id = None
            lead_custom_fields: dict = {}
            try:
                lead = await find_or_create_lead(
                    db,
                    org_id=bot_config.org_id,
                    phone_number=queued_call.contact_phone,
                    contact_name=queued_call.contact_name,
                    ghl_contact_id=queued_call.ghl_contact_id,
                    extra_vars=queued_call.extra_vars,
                )
                lead_id = lead.id
                lead_custom_fields = dict(lead.custom_fields or {})
            except Exception as e:
                logger.error(
                    "lead_auto_create_failed",
                    queue_id=str(queue_id),
                    error=str(e),
                )
                # Non-fatal — proceed without lead linkage

            # Fill prompt template — copy context_variables to avoid mutating cached bot_config
            ctx_vars = bot_config.context_variables or {}
            template_vars = dict(ctx_vars) if isinstance(ctx_vars, dict) else {}
            # Lead's saved custom_fields go in first as baseline
            if lead_custom_fields:
                template_vars.update(_normalize_template_vars(lead_custom_fields))
            template_vars.update(
                contact_name=queued_call.contact_name,
                agent_name=bot_config.agent_name,
                company_name=bot_config.company_name,
                location=bot_config.location or "",
                event_name=bot_config.event_name or "",
                event_date=bot_config.event_date or "",
                event_time=bot_config.event_time or "",
            )
            # Normalize extra_vars independently so webhook values always win
            # over context_variables defaults (extra_vars may use camelCase aliases
            # like "eventHost" which need to map to "event_host")
            raw_extras = queued_call.extra_vars or {}
            normalized_extras = _normalize_template_vars(raw_extras)
            template_vars.update(normalized_extras)
            template_vars = _normalize_template_vars(template_vars)

            logger.info(
                "queue_fill_prompt_debug",
                queue_id=str(queue_id),
                raw_extra_vars=raw_extras,
                lead_custom_fields=lead_custom_fields,
                normalized_extras={k: v for k, v in normalized_extras.items() if k != template_vars.get(k, v)},
                event_host=template_vars.get("event_host"),
                customer_profession=template_vars.get("customer_profession"),
            )

            filled_prompt = fill_prompt_template(
                bot_config.system_prompt_template, **template_vars
            )

            # Inject call memory if enabled for this bot
            if getattr(bot_config, "call_memory_enabled", False):
                memory_count = getattr(bot_config, "call_memory_count", 3)
                try:
                    memory_section = await build_call_memory_prompt(
                        db,
                        org_id=bot_config.org_id,
                        contact_phone=queued_call.contact_phone,
                        max_calls=memory_count,
                    )
                    if memory_section:
                        filled_prompt = filled_prompt + "\n" + memory_section
                        logger.info(
                            "call_memory_injected",
                            queue_id=str(queue_id),
                            phone=queued_call.contact_phone,
                        )
                except Exception as e:
                    logger.error(
                        "call_memory_failed",
                        queue_id=str(queue_id),
                        error=str(e),
                    )
                    # Non-fatal — proceed without memory

            # Create call log
            call_sid = str(uuid4())
            call_log = CallLog(
                org_id=bot_config.org_id,
                bot_id=bot_config.id,
                call_sid=call_sid,
                contact_name=queued_call.contact_name,
                contact_phone=queued_call.contact_phone,
                ghl_contact_id=queued_call.ghl_contact_id,
                lead_id=lead_id,
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

            # Resolve telephony credentials (org-level first, bot-level fallback)
            provider, from_number, auth_creds = await _resolve_telephony(
                db, bot_config
            )
            base_url = settings.PUBLIC_BASE_URL

            if provider == "twilio":
                provider_uuid = await twilio_make_call(
                    account_sid=auth_creds["account_sid"],
                    auth_token=auth_creds["auth_token"],
                    from_number=from_number,
                    to_number=queued_call.contact_phone,
                    answer_url=f"{base_url}/twilio/answer/{call_sid}",
                    status_callback_url=f"{base_url}/twilio/event/{call_sid}",
                )
            else:
                provider_uuid = await plivo_make_call(
                    auth_id=auth_creds["auth_id"],
                    auth_token=auth_creds["auth_token"],
                    from_number=from_number,
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
                if queued_call.campaign_id and queued_call.campaign_lead_id:
                    await _handle_campaign_call_result(
                        db, queued_call.campaign_id, queued_call.campaign_lead_id,
                        call_log_id=call_log.id, success=False,
                    )
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

            # Handle campaign lead progression
            if queued_call.campaign_id and queued_call.campaign_lead_id:
                await _handle_campaign_call_result(
                    db,
                    campaign_id=queued_call.campaign_id,
                    campaign_lead_id=queued_call.campaign_lead_id,
                    call_log_id=call_log.id,
                    success=True,
                )

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

            # Handle campaign lead failure
            if queued_call.campaign_id and queued_call.campaign_lead_id:
                await _handle_campaign_call_result(
                    db,
                    campaign_id=queued_call.campaign_id,
                    campaign_lead_id=queued_call.campaign_lead_id,
                    call_log_id=None,
                    success=False,
                )

            tripped = await circuit_breaker.record_failure(db, bot_id, str(e)[:200])
            await db.commit()


async def _handle_campaign_call_result(
    db: AsyncSession,
    campaign_id,
    campaign_lead_id,
    call_log_id,
    success: bool,
):
    """Update CampaignLead and Campaign after a campaign call completes or fails.

    Also enqueues the next batch of leads if there are available slots.
    """
    try:
        # Update the CampaignLead record
        cl_result = await db.execute(
            select(CampaignLead)
            .where(CampaignLead.id == campaign_lead_id)
            .with_for_update()
        )
        campaign_lead = cl_result.scalar_one_or_none()
        if not campaign_lead:
            logger.warning(
                "campaign_lead_not_found",
                campaign_lead_id=str(campaign_lead_id),
            )
            return

        campaign_lead.call_log_id = call_log_id

        if success:
            # Call was initiated successfully — keep status as "processing" until
            # the call actually ends (finalize_campaign_call will update it then).
            # Don't increment any counters yet.
            await db.commit()
            return

        # Call initiation failed — mark as failed now.
        campaign_lead.status = "failed"
        campaign_lead.processed_at = datetime.now(timezone.utc)

        # Update Campaign counters with row lock
        camp_result = await db.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .with_for_update()
        )
        campaign = camp_result.scalar_one_or_none()
        if not campaign:
            logger.warning("campaign_not_found", campaign_id=str(campaign_id))
            await db.commit()
            return

        campaign.failed_leads += 1

        # Check if campaign is still running (could have been paused/cancelled)
        if campaign.status != "running":
            await db.commit()
            logger.info(
                "campaign_not_running_skip_enqueue",
                campaign_id=str(campaign_id),
                status=campaign.status,
            )
            return

        # Check if all leads are done
        remaining_result = await db.execute(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status.in_(["queued", "processing"]),
            )
        )
        remaining = remaining_result.scalar_one()

        if remaining == 0:
            campaign.status = "completed"
            campaign.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "campaign_completed",
                campaign_id=str(campaign_id),
                completed=campaign.completed_leads,
                failed=campaign.failed_leads,
            )
            return

        # Enqueue next batch of leads to fill available concurrency slots
        processing_result = await db.execute(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status == "processing",
            )
        )
        currently_processing = processing_result.scalar_one()
        slots = max(0, campaign.concurrency_limit - currently_processing)

        if slots > 0:
            # Fetch next queued leads
            next_leads_result = await db.execute(
                select(CampaignLead)
                .where(
                    CampaignLead.campaign_id == campaign_id,
                    CampaignLead.status == "queued",
                )
                .order_by(CampaignLead.position.asc())
                .limit(slots)
                .with_for_update(skip_locked=True)
            )
            next_leads = next_leads_result.scalars().all()

            if next_leads:
                # Batch-fetch lead details
                lead_ids = [cl.lead_id for cl in next_leads]
                lead_result = await db.execute(
                    select(Lead).where(Lead.id.in_(lead_ids))
                )
                lead_map = {ld.id: ld for ld in lead_result.scalars().all()}

                enqueued = 0
                for cl in next_leads:
                    lead = lead_map.get(cl.lead_id)
                    if not lead:
                        cl.status = "failed"
                        cl.processed_at = datetime.now(timezone.utc)
                        campaign.failed_leads += 1
                        continue

                    normalized_phone = normalize_phone_india(lead.phone_number)
                    queued_call = QueuedCall(
                        org_id=campaign.org_id,
                        bot_id=campaign.bot_config_id,
                        contact_name=lead.contact_name,
                        contact_phone=normalized_phone,
                        source="campaign",
                        status="queued",
                        priority=0,
                        campaign_id=campaign.id,
                        campaign_lead_id=cl.id,
                        extra_vars={
                            "campaign_id": str(campaign.id),
                            "campaign_lead_id": str(cl.id),
                        },
                    )
                    db.add(queued_call)
                    cl.status = "processing"
                    enqueued += 1

                if enqueued:
                    logger.info(
                        "campaign_next_batch_enqueued",
                        campaign_id=str(campaign_id),
                        enqueued=enqueued,
                    )

        await db.commit()

    except Exception:
        logger.exception(
            "campaign_result_handler_error",
            campaign_id=str(campaign_id),
            campaign_lead_id=str(campaign_lead_id),
        )
        # Don't let campaign tracking errors crash the processor
        try:
            await db.rollback()
        except Exception:
            pass


async def finalize_campaign_call(call_log_id: UUID, call_status: str):
    """Update CampaignLead and Campaign when a campaign call actually ends.

    Called from plivo_event/twilio_event webhook when call outcome is known.
    """
    try:
        async with get_db_session() as db:
            # Find QueuedCall by call_log_id to get campaign references
            qc_result = await db.execute(
                select(QueuedCall).where(
                    QueuedCall.call_log_id == call_log_id,
                    QueuedCall.campaign_id.isnot(None),
                )
            )
            queued_call = qc_result.scalar_one_or_none()
            if not queued_call:
                return  # Not a campaign call

            # Update CampaignLead
            cl_result = await db.execute(
                select(CampaignLead)
                .where(CampaignLead.id == queued_call.campaign_lead_id)
                .with_for_update()
            )
            campaign_lead = cl_result.scalar_one_or_none()
            if not campaign_lead or campaign_lead.status != "processing":
                return  # Already finalized or not in expected state

            # Determine outcome: "completed" = actually answered, "failed" = not answered
            answered = call_status in ("completed", "in_progress")
            campaign_lead.status = "completed" if answered else "failed"
            campaign_lead.processed_at = datetime.now(timezone.utc)

            # Update Campaign counters
            camp_result = await db.execute(
                select(Campaign)
                .where(Campaign.id == queued_call.campaign_id)
                .with_for_update()
            )
            campaign = camp_result.scalar_one_or_none()
            if not campaign:
                await db.commit()
                return

            if answered:
                campaign.completed_leads += 1
            else:
                campaign.failed_leads += 1

            # Check if campaign is done
            if campaign.status == "running":
                remaining_result = await db.execute(
                    select(func.count())
                    .select_from(CampaignLead)
                    .where(
                        CampaignLead.campaign_id == campaign.id,
                        CampaignLead.status.in_(["queued", "processing"]),
                    )
                )
                remaining = remaining_result.scalar_one()

                if remaining == 0:
                    campaign.status = "completed"
                    campaign.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(
                        "campaign_completed",
                        campaign_id=str(campaign.id),
                        completed=campaign.completed_leads,
                        failed=campaign.failed_leads,
                    )
                    return

                # Enqueue next batch to fill available concurrency slots
                processing_result = await db.execute(
                    select(func.count())
                    .select_from(CampaignLead)
                    .where(
                        CampaignLead.campaign_id == campaign.id,
                        CampaignLead.status == "processing",
                    )
                )
                currently_processing = processing_result.scalar_one()
                slots = max(0, campaign.concurrency_limit - currently_processing)

                if slots > 0:
                    next_leads_result = await db.execute(
                        select(CampaignLead)
                        .where(
                            CampaignLead.campaign_id == campaign.id,
                            CampaignLead.status == "queued",
                        )
                        .order_by(CampaignLead.position.asc())
                        .limit(slots)
                        .with_for_update(skip_locked=True)
                    )
                    next_leads = next_leads_result.scalars().all()

                    if next_leads:
                        lead_ids = [cl.lead_id for cl in next_leads]
                        lead_result = await db.execute(
                            select(Lead).where(Lead.id.in_(lead_ids))
                        )
                        lead_map = {ld.id: ld for ld in lead_result.scalars().all()}

                        enqueued = 0
                        for cl in next_leads:
                            lead = lead_map.get(cl.lead_id)
                            if not lead:
                                cl.status = "failed"
                                cl.processed_at = datetime.now(timezone.utc)
                                campaign.failed_leads += 1
                                continue

                            normalized_phone = normalize_phone_india(lead.phone_number)
                            queued_call_new = QueuedCall(
                                org_id=campaign.org_id,
                                bot_id=campaign.bot_config_id,
                                contact_name=lead.contact_name,
                                contact_phone=normalized_phone,
                                source="campaign",
                                status="queued",
                                priority=0,
                                campaign_id=campaign.id,
                                campaign_lead_id=cl.id,
                                extra_vars={
                                    "campaign_id": str(campaign.id),
                                    "campaign_lead_id": str(cl.id),
                                },
                            )
                            db.add(queued_call_new)
                            cl.status = "processing"
                            enqueued += 1

                        if enqueued:
                            logger.info(
                                "campaign_next_batch_enqueued",
                                campaign_id=str(campaign.id),
                                enqueued=enqueued,
                            )

            await db.commit()
            logger.info(
                "campaign_call_finalized",
                campaign_id=str(queued_call.campaign_id),
                campaign_lead_id=str(queued_call.campaign_lead_id),
                call_status=call_status,
                outcome="completed" if answered else "failed",
            )
    except Exception:
        logger.exception(
            "campaign_call_finalize_error",
            call_log_id=str(call_log_id),
        )


async def schedule_auto_retry(call_log_id: UUID, bot_config_loader):
    """Re-queue a no-answer call for automatic retry if callback is enabled.

    Called from plivo_event / twilio_event when call status is 'no_answer'.
    Uses step-based callback_schedule if configured, falls back to old
    flat fields (callback_retry_delay_hours + callback_max_retries) for
    backward compatibility during Phase 1 migration.
    """
    try:
        async with get_db_session() as db:
            # 1. Load call log
            result = await db.execute(
                select(CallLog).where(CallLog.id == call_log_id)
            )
            call_log = result.scalar_one_or_none()
            if not call_log or not call_log.context_data:
                return

            # 2. Skip if user asked not to be called again (DND / rejection)
            meta = call_log.metadata_ or {}
            llm_reason = (meta.get("llm_end_reason") or "").lower()
            _DND_PHRASES = (
                "don't call", "do not call", "stop calling", "not interested",
                "wrong number", "not to be called", "asked not to",
                "nahi chahiye", "zaroorat nahi", "mat karo call",
            )
            if any(phrase in llm_reason for phrase in _DND_PHRASES):
                logger.info(
                    "auto_retry_skip_dnd",
                    call_log_id=str(call_log_id),
                    phone=call_log.contact_phone,
                    llm_end_reason=llm_reason,
                )
                return

            if meta.get("dnd_detected"):
                logger.info(
                    "auto_retry_skip_dnd_flag",
                    call_log_id=str(call_log_id),
                    phone=call_log.contact_phone,
                    dnd_reason=meta.get("dnd_reason"),
                )
                return

            # 3. Skip campaign calls — campaigns have their own retry logic
            qc_result = await db.execute(
                select(QueuedCall).where(
                    QueuedCall.call_log_id == call_log_id,
                    QueuedCall.campaign_id.isnot(None),
                )
            )
            if qc_result.scalar_one_or_none():
                return

            # 3. Load bot config and check callback_enabled
            bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
            if not bot_config or not getattr(bot_config, "callback_enabled", False):
                return

            # 4. Find original queued call to get retry_count and extra_vars
            orig_result = await db.execute(
                select(QueuedCall)
                .where(QueuedCall.call_log_id == call_log_id)
                .order_by(QueuedCall.created_at.desc())
                .limit(1)
            )
            original_qc = orig_result.scalar_one_or_none()

            # 5. Skip sequence-sourced calls — they have their own follow-up
            if original_qc and original_qc.source == "sequence":
                return

            # 6. Deduplication — skip if ANY pending/queued call exists for this phone+bot
            existing = await db.execute(
                select(QueuedCall.id).where(
                    QueuedCall.contact_phone == call_log.contact_phone,
                    QueuedCall.bot_id == call_log.bot_id,
                    QueuedCall.status.in_(["queued", "processing"]),
                ).limit(1)
            )
            if existing.scalar():
                logger.info(
                    "auto_retry_dedup_skip",
                    call_log_id=str(call_log_id),
                    phone=call_log.contact_phone,
                )
                return

            # 7. Rate limit — skip if any call to this phone+bot completed recently
            delay_hours = getattr(bot_config, "callback_retry_delay_hours", 2.0)
            min_gap = datetime.now(timezone.utc) - timedelta(hours=delay_hours)
            recent_call = await db.execute(
                select(CallLog.id).where(
                    CallLog.contact_phone == call_log.contact_phone,
                    CallLog.bot_id == call_log.bot_id,
                    CallLog.created_at >= min_gap,
                    CallLog.id != call_log_id,
                    CallLog.status == "completed",
                ).limit(1)
            )
            if recent_call.scalar():
                logger.info(
                    "auto_retry_rate_limit_skip",
                    call_log_id=str(call_log_id),
                    phone=call_log.contact_phone,
                    min_gap_hours=delay_hours,
                )
                return

            current_retry = (original_qc.retry_count if original_qc else 0)

            # 7. Compute scheduled_at — new step-based or old flat fallback
            schedule = getattr(bot_config, "callback_schedule", None)
            if schedule and schedule.get("steps"):
                steps = schedule["steps"]
                if current_retry >= len(steps):
                    logger.info(
                        "auto_retry_schedule_exhausted",
                        call_log_id=str(call_log_id),
                        phone=call_log.contact_phone,
                        retry_count=current_retry,
                        max_steps=len(steps),
                    )
                    return
                from app.services.smart_retry import compute_scheduled_at
                step = steps[current_retry]
                scheduled_at = compute_scheduled_at(step, bot_config)
            else:
                # Phase 1 fallback: old flat fields
                max_retries = getattr(bot_config, "callback_max_retries", 3)
                delay_hours = getattr(bot_config, "callback_retry_delay_hours", 2.0)
                if current_retry >= max_retries:
                    logger.info(
                        "auto_retry_max_reached",
                        call_log_id=str(call_log_id),
                        retry_count=current_retry,
                        max_retries=max_retries,
                    )
                    return
                scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

            retry_call = QueuedCall(
                org_id=call_log.org_id,
                bot_id=call_log.bot_id,
                contact_name=call_log.contact_name,
                contact_phone=call_log.contact_phone,
                ghl_contact_id=call_log.ghl_contact_id,
                extra_vars=(original_qc.extra_vars if original_qc else {}),
                source="auto_retry",
                status="queued",
                priority=0,
                scheduled_at=scheduled_at,
                retry_count=current_retry + 1,
                original_call_sid=call_log.call_sid,
            )
            db.add(retry_call)
            await db.commit()

            logger.info(
                "auto_retry_scheduled",
                call_log_id=str(call_log_id),
                phone=call_log.contact_phone,
                retry_number=current_retry + 1,
                scheduled_at=scheduled_at.isoformat(),
                used_schedule=bool(schedule and schedule.get("steps")),
            )

    except Exception:
        logger.exception(
            "auto_retry_schedule_error",
            call_log_id=str(call_log_id),
        )
