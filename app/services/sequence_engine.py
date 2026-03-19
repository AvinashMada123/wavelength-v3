"""Core sequence engine — trigger evaluation, instance creation, touchpoint processing, reply handling."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequence import (
    SequenceInstance,
    SequenceStep,
    SequenceTemplate,
    SequenceTouchpoint,
)
from app.models.messaging_provider import MessagingProvider
from app.models.call_queue import QueuedCall
from app.services import anthropic_client, messaging_client

logger = structlog.get_logger(__name__)

INTEREST_LEVELS = {"low": 1, "medium": 2, "high": 3}


def parse_bot_event_date(event_date_str: str, event_time_str: str = "") -> str | None:
    """Convert bot config free-text event_date + event_time to ISO string.

    Handles formats like "7th March 2026" + "7:30 PM".
    Returns ISO string or None if unparseable.
    """
    import re as _re
    clean = _re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", event_date_str)
    parsed = None
    for fmt in ("%d %B %Y", "%B %d %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(clean.strip(), fmt)
            break
        except ValueError:
            continue
    if not parsed:
        return None
    if event_time_str:
        for tfmt in ("%I:%M %p", "%H:%M", "%I %p"):
            try:
                t = datetime.strptime(event_time_str.strip(), tfmt)
                parsed = parsed.replace(hour=t.hour, minute=t.minute)
                break
            except ValueError:
                continue
    return parsed.isoformat()


# ---------------------------------------------------------------------------
# Pure functions (testable without DB)
# ---------------------------------------------------------------------------

def _calculate_scheduled_time(
    timing_type: str,
    timing_value: dict,
    signup_time: datetime,
    event_date: datetime | None,
    prev_scheduled: datetime | None,
) -> datetime:
    """Calculate absolute scheduled time from timing config."""
    if timing_type == "relative_to_signup":
        delta = timedelta(
            hours=timing_value.get("hours", 0),
            days=timing_value.get("days", 0),
            minutes=timing_value.get("minutes", 0),
        )
        base = signup_time + delta
        # If a specific time is set, override hour/minute
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        return base

    elif timing_type == "relative_to_event":
        if not event_date:
            raise ValueError("relative_to_event requires event_date in context_data")
        days_offset = timing_value.get("days", 0)
        base = event_date + timedelta(days=days_offset)
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            hours = timing_value.get("hours", 0)
            base = base + timedelta(hours=hours)
        return base

    elif timing_type == "relative_to_previous_step":
        if not prev_scheduled:
            # Fallback to signup if no previous step
            prev_scheduled = signup_time
        delta = timedelta(
            hours=timing_value.get("hours", 0),
            days=timing_value.get("days", 0),
            minutes=timing_value.get("minutes", 0),
        )
        base = prev_scheduled + delta
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        return base

    raise ValueError(f"Unknown timing_type: {timing_type}")


def _should_skip(skip_conditions: dict | None, context_data: dict) -> bool:
    """Evaluate if a step should be skipped based on context data."""
    if not skip_conditions:
        return False
    field = skip_conditions.get("field", "")
    expected = skip_conditions.get("equals")
    actual = context_data.get(field)
    if expected is not None:
        return str(actual) == str(expected)
    not_equals = skip_conditions.get("not_equals")
    if not_equals is not None:
        return str(actual) != str(not_equals)
    return False


def _matches_trigger_conditions(conditions: dict, analysis) -> bool:
    """Check if a call analysis matches template trigger conditions."""
    if not conditions:
        return True

    # Check goal_outcome
    if "goal_outcome" in conditions:
        allowed = conditions["goal_outcome"]
        if isinstance(allowed, list) and analysis.goal_outcome not in allowed:
            return False

    # Check min_interest
    if "min_interest" in conditions:
        min_level = INTEREST_LEVELS.get(conditions["min_interest"], 0)
        actual_level = INTEREST_LEVELS.get(getattr(analysis, "interest_level", "low"), 0)
        if actual_level < min_level:
            return False

    return True


def _snapshot_step(step: SequenceStep) -> dict:
    """Create a JSON snapshot of step config for touchpoint."""
    return {
        "name": step.name,
        "channel": step.channel,
        "content_type": step.content_type,
        "whatsapp_template_name": step.whatsapp_template_name,
        "whatsapp_template_params": step.whatsapp_template_params,
        "ai_prompt": step.ai_prompt,
        "ai_model": step.ai_model,
        "voice_bot_id": str(step.voice_bot_id) if step.voice_bot_id else None,
        "expects_reply": step.expects_reply,
        "reply_handler": step.reply_handler,
        "skip_conditions": step.skip_conditions,
    }


# ---------------------------------------------------------------------------
# DB-dependent functions
# ---------------------------------------------------------------------------

async def evaluate_trigger(
    db: AsyncSession,
    org_id: uuid.UUID,
    bot_id: uuid.UUID,
    analysis,
    lead,
    call_log,
) -> SequenceInstance | None:
    """After a call completes, check if any sequence template should fire."""
    # Find active templates for this bot (or org-wide)
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,
            SequenceTemplate.trigger_type == "post_call",
            (SequenceTemplate.bot_id == bot_id) | (SequenceTemplate.bot_id.is_(None)),
        )
    )
    templates = result.scalars().all()

    for template in templates:
        if not _matches_trigger_conditions(template.trigger_conditions, analysis):
            continue

        # Check max_active_per_lead
        active_count_result = await db.execute(
            select(func.count()).where(
                SequenceInstance.template_id == template.id,
                SequenceInstance.lead_id == lead.id,
                SequenceInstance.status == "active",
            )
        )
        active_count = active_count_result.scalar() or 0
        if active_count >= template.max_active_per_lead:
            logger.info(
                "sequence_trigger_skipped_max_active",
                template_id=str(template.id),
                lead_id=str(lead.id),
                active_count=active_count,
            )
            continue

        # Build context_data from analysis + lead + call_log
        context_data = {
            "contact_name": lead.contact_name or "",
            "contact_phone": lead.phone_number or "",
            "profession": getattr(analysis, "captured_data", {}).get("profession", ""),
            "challenge": getattr(analysis, "captured_data", {}).get("challenge", ""),
            "anchor_task": getattr(analysis, "captured_data", {}).get("anchor_task", ""),
            "tried_ai": getattr(analysis, "captured_data", {}).get("tried_ai", ""),
            "interest_level": getattr(analysis, "interest_level", ""),
            "goal_outcome": getattr(analysis, "goal_outcome", ""),
            "sentiment": getattr(analysis, "sentiment", ""),
            "call_summary": getattr(analysis, "summary", ""),
        }
        # Merge any captured_data fields
        if hasattr(analysis, "captured_data") and analysis.captured_data:
            for k, v in analysis.captured_data.items():
                if k not in context_data:
                    context_data[k] = v

        instance = await create_instance(
            db,
            template_id=template.id,
            org_id=org_id,
            lead_id=lead.id,
            trigger_call_id=call_log.id if call_log else None,
            context_data=context_data,
        )
        if instance:
            logger.info(
                "sequence_triggered",
                template=template.name,
                lead_id=str(lead.id),
                instance_id=str(instance.id),
            )
            return instance

    return None


async def create_instance(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    lead_id: uuid.UUID,
    trigger_call_id: uuid.UUID | None,
    context_data: dict,
) -> SequenceInstance | None:
    """Create a sequence instance + all touchpoints with calculated times."""
    # Load steps
    result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.template_id == template_id, SequenceStep.is_active == True)
        .order_by(SequenceStep.step_order)
    )
    steps = result.scalars().all()
    if not steps:
        logger.warning("sequence_create_no_steps", template_id=str(template_id))
        return None

    # Merge template variable defaults into context_data (caller values take precedence)
    tmpl_result = await db.execute(
        select(SequenceTemplate).where(SequenceTemplate.id == template_id)
    )
    template_obj = tmpl_result.scalar_one_or_none()
    if template_obj and template_obj.variables:
        for var in template_obj.variables:
            if var.get("key") and var.get("default_value"):
                context_data.setdefault(var["key"], var["default_value"])

    # Create instance
    now = datetime.now(timezone.utc)
    instance = SequenceInstance(
        org_id=org_id,
        template_id=template_id,
        lead_id=lead_id,
        trigger_call_id=trigger_call_id,
        status="active",
        context_data=context_data,
        started_at=now,
    )
    db.add(instance)
    await db.flush()  # Get instance.id

    # Resolve default messaging provider for this org
    provider_result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.org_id == org_id,
            MessagingProvider.is_default == True,
        )
    )
    default_provider = provider_result.scalar_one_or_none()

    # Create touchpoints
    prev_scheduled = None
    for step in steps:
        # Resolve event_date per-step from context_data
        step_event_date = None
        if step.timing_type == "relative_to_event":
            event_var = step.timing_value.get("event_variable") or "event_date"
            raw = context_data.get(event_var)
            if not raw:
                logger.error(
                    "sequence_create_missing_event_variable",
                    template_id=str(template_id),
                    variable=event_var,
                )
                return None
            try:
                step_event_date = datetime.fromisoformat(str(raw))
                if step_event_date.tzinfo is None:
                    step_event_date = step_event_date.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                logger.error(
                    "sequence_create_unparseable_event_variable",
                    template_id=str(template_id),
                    variable=event_var,
                    value=str(raw),
                )
                return None

        scheduled_at = _calculate_scheduled_time(
            timing_type=step.timing_type,
            timing_value=step.timing_value,
            signup_time=now,
            event_date=step_event_date,
            prev_scheduled=prev_scheduled,
        )

        # Determine initial status
        status = "pending"
        if _should_skip(step.skip_conditions, context_data):
            status = "skipped"

        touchpoint = SequenceTouchpoint(
            instance_id=instance.id,
            step_id=step.id,
            org_id=org_id,
            lead_id=lead_id,
            step_order=step.step_order,
            step_snapshot=_snapshot_step(step),
            status=status,
            scheduled_at=scheduled_at,
            messaging_provider_id=default_provider.id if default_provider else None,
        )
        db.add(touchpoint)
        prev_scheduled = scheduled_at

    await db.flush()
    return instance


async def process_touchpoint(db: AsyncSession, touchpoint: SequenceTouchpoint) -> None:
    """Process a single due touchpoint: generate content, send, update status."""
    snapshot = touchpoint.step_snapshot or {}
    channel = snapshot.get("channel", "")
    content_type = snapshot.get("content_type", "")

    # Load instance for context_data
    inst_result = await db.execute(
        select(SequenceInstance).where(SequenceInstance.id == touchpoint.instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance or instance.status != "active":
        touchpoint.status = "skipped"
        await db.commit()
        return

    context = instance.context_data or {}
    phone = context.get("contact_phone", "")

    # Re-check skip conditions
    if _should_skip(snapshot.get("skip_conditions"), context):
        touchpoint.status = "skipped"
        await db.commit()
        return

    # --- Generate content if AI ---
    if content_type == "ai_generated" and snapshot.get("ai_prompt"):
        touchpoint.status = "generating"
        await db.commit()
        try:
            generated = await anthropic_client.generate_content(
                prompt=snapshot["ai_prompt"],
                variables=context,
                model=snapshot.get("ai_model", "claude-sonnet"),
                org_id=str(touchpoint.org_id),
                reference=f"sequence_tp_{touchpoint.id}",
            )
            touchpoint.generated_content = generated
        except Exception as e:
            touchpoint.status = "failed"
            touchpoint.error_message = f"AI generation failed: {e}"
            touchpoint.retry_count += 1
            await db.commit()
            return

    # --- Send via channel ---
    if channel == "voice_call":
        # Create a QueuedCall for the specified bot
        bot_id = snapshot.get("voice_bot_id")
        if not bot_id:
            touchpoint.status = "failed"
            touchpoint.error_message = "No voice_bot_id configured for voice_call step"
            await db.commit()
            return

        queued_call = QueuedCall(
            org_id=touchpoint.org_id,
            bot_id=uuid.UUID(bot_id) if isinstance(bot_id, str) else bot_id,
            contact_name=context.get("contact_name", ""),
            contact_phone=phone,
            ghl_contact_id=context.get("ghl_contact_id"),
            source="sequence",
            status="queued",
            priority=1,
            extra_vars={
                "sequence_instance_id": str(touchpoint.instance_id),
                "sequence_touchpoint_id": str(touchpoint.id),
                "step_name": snapshot.get("name", ""),
            },
        )
        db.add(queued_call)
        await db.flush()
        touchpoint.queued_call_id = queued_call.id
        touchpoint.status = "scheduled"
        await db.commit()
        logger.info("sequence_voice_call_queued", touchpoint_id=str(touchpoint.id), bot_id=bot_id)
        return

    # WhatsApp / SMS delivery
    if not touchpoint.messaging_provider_id:
        touchpoint.status = "failed"
        touchpoint.error_message = "No messaging provider configured"
        await db.commit()
        return

    prov_result = await db.execute(
        select(MessagingProvider).where(MessagingProvider.id == touchpoint.messaging_provider_id)
    )
    provider = prov_result.scalar_one_or_none()
    if not provider:
        touchpoint.status = "failed"
        touchpoint.error_message = "Messaging provider not found"
        await db.commit()
        return

    result = None
    now = datetime.now(timezone.utc)

    if channel == "whatsapp_template":
        # Interpolate template params
        params = snapshot.get("whatsapp_template_params") or []
        resolved_params = []
        for p in params:
            val = p.get("value", "")
            # Replace {{var}} with context values
            from app.services.anthropic_client import _interpolate_variables
            val = _interpolate_variables(val, context)
            resolved_params.append({"name": p.get("name", ""), "value": val})

        # If AI-generated content should be injected into a template param
        if touchpoint.generated_content and resolved_params:
            # Find param that references {{ai_content}} or is empty, fill with generated
            for rp in resolved_params:
                if "{{ai_content}}" in rp.get("value", "") or rp.get("value", "") == "":
                    rp["value"] = touchpoint.generated_content
                    break

        result = await messaging_client.send_template(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            template_name=snapshot.get("whatsapp_template_name", ""),
            params=resolved_params,
        )
        if result.success:
            touchpoint.session_window_expires_at = now + timedelta(hours=24)

    elif channel == "whatsapp_session":
        content = touchpoint.generated_content or ""
        if not content:
            touchpoint.status = "failed"
            touchpoint.error_message = "No content for session message"
            await db.commit()
            return
        result = await messaging_client.send_session_message(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            text=content,
        )

    elif channel == "sms":
        content = touchpoint.generated_content or ""
        result = await messaging_client.send_sms(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            text=content,
        )

    # Update touchpoint status
    if result and result.success:
        if snapshot.get("expects_reply"):
            touchpoint.status = "awaiting_reply"
        else:
            touchpoint.status = "sent"
        touchpoint.sent_at = now
    elif result:
        touchpoint.status = "failed"
        touchpoint.error_message = result.error
        touchpoint.retry_count += 1
    else:
        touchpoint.status = "failed"
        touchpoint.error_message = "No delivery result returned"
        touchpoint.retry_count += 1

    await db.commit()

    # Check if sequence is complete
    await _check_instance_completion(db, touchpoint.instance_id)


async def handle_reply(db: AsyncSession, phone: str, message_text: str) -> bool:
    """Handle an incoming WhatsApp reply. Returns True if processed."""
    # Normalize phone
    clean_phone = phone.lstrip("+")

    # Find most recent awaiting_reply touchpoint for this phone, within 48hrs
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    result = await db.execute(
        select(SequenceTouchpoint)
        .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
        .where(
            SequenceTouchpoint.status == "awaiting_reply",
            SequenceInstance.status == "active",
            SequenceTouchpoint.sent_at >= cutoff,
            SequenceInstance.context_data["contact_phone"].astext.contains(clean_phone[-10:]),
        )
        .order_by(SequenceTouchpoint.sent_at.desc())
        .limit(1)
    )
    touchpoint = result.scalar_one_or_none()
    if not touchpoint:
        logger.debug("reply_no_matching_touchpoint", phone=phone)
        return False

    snapshot = touchpoint.step_snapshot or {}
    reply_handler = snapshot.get("reply_handler")
    touchpoint.reply_text = message_text
    # Reset session window on reply (WhatsApp 24hr window resets from user's last message)
    touchpoint.session_window_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # Load instance for context
    inst_result = await db.execute(
        select(SequenceInstance).where(SequenceInstance.id == touchpoint.instance_id)
    )
    instance = inst_result.scalar_one_or_none()

    if reply_handler and reply_handler.get("action") == "ai_respond":
        # Check session window
        now = datetime.now(timezone.utc)
        if touchpoint.session_window_expires_at and now > touchpoint.session_window_expires_at:
            logger.warning("reply_session_window_expired", touchpoint_id=str(touchpoint.id))
            touchpoint.status = "replied"
            touchpoint.error_message = "Session window expired, AI response not sent"
            await db.commit()
            return True

        # Generate AI response
        try:
            context = dict(instance.context_data) if instance else {}
            context["reply_text"] = message_text
            response = await anthropic_client.generate_content(
                prompt=reply_handler["ai_prompt"],
                variables=context,
                model=reply_handler.get("ai_model", "claude-sonnet"),
            )
            touchpoint.reply_response = response

            # Send response via WhatsApp session
            if touchpoint.messaging_provider_id:
                prov_result = await db.execute(
                    select(MessagingProvider).where(
                        MessagingProvider.id == touchpoint.messaging_provider_id
                    )
                )
                provider = prov_result.scalar_one_or_none()
                if provider:
                    contact_phone = (instance.context_data or {}).get("contact_phone", phone)
                    await messaging_client.send_session_message(
                        encrypted_creds=provider.credentials,
                        provider_type=provider.provider_type,
                        phone=contact_phone,
                        text=response,
                    )

            # Save to context_data if configured
            if reply_handler.get("save_field") and instance:
                updated_context = dict(instance.context_data)
                updated_context[reply_handler["save_field"]] = message_text
                instance.context_data = updated_context

        except Exception as e:
            logger.exception("reply_ai_generation_failed", touchpoint_id=str(touchpoint.id))
            touchpoint.error_message = f"AI response generation failed: {e}"

    touchpoint.status = "replied"
    await db.commit()

    logger.info("reply_processed", touchpoint_id=str(touchpoint.id), phone=phone)
    return True


async def _check_instance_completion(db: AsyncSession, instance_id: uuid.UUID) -> None:
    """Check if all touchpoints are terminal and mark instance completed."""
    result = await db.execute(
        select(func.count()).where(
            SequenceTouchpoint.instance_id == instance_id,
            SequenceTouchpoint.status.in_(["pending", "generating", "scheduled", "awaiting_reply"]),
        )
    )
    remaining = result.scalar() or 0
    if remaining == 0:
        inst_result = await db.execute(
            select(SequenceInstance).where(SequenceInstance.id == instance_id)
        )
        instance = inst_result.scalar_one_or_none()
        if instance and instance.status == "active":
            instance.status = "completed"
            instance.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("sequence_completed", instance_id=str(instance_id))
