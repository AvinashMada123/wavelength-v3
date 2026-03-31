"""n8n webhook automation service.

Fires configurable HTTP webhooks at pre-call and post-call stages,
with conditional logic and rich payload assembly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Custom JSON encoder for payload serialization
# ---------------------------------------------------------------------------


class _PayloadEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _json_serialize(data: dict) -> str:
    return json.dumps(data, cls=_PayloadEncoder)


# ---------------------------------------------------------------------------
# Dot-notation field resolver
# ---------------------------------------------------------------------------


def _resolve_field(field: str, data: dict) -> Any:
    """Resolve a dot-notation field path against a nested dict.

    Example: 'captured_data.email' → data['captured_data']['email']
    Returns None if any intermediate key is missing or not a dict.
    """
    parts = field.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------


def evaluate_conditions(
    conditions: list[dict] | None,
    condition_logic: str | None,
    call_data: dict,
) -> bool:
    """Evaluate a list of conditions against call data.

    Returns True if conditions are met (or empty/None = always fire).
    """
    if not conditions:
        return True

    logic = condition_logic or "all"
    results = [_eval_single(c, call_data) for c in conditions]
    return all(results) if logic == "all" else any(results)


def _eval_single(condition: dict, call_data: dict) -> bool:
    """Evaluate a single condition against call data."""
    field = condition.get("field", "")
    operator = condition.get("operator", "")
    expected = condition.get("value")

    actual = _resolve_field(field, call_data)

    try:
        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "in":
            if not isinstance(expected, list):
                return False
            return actual in expected
        if operator == "not_in":
            if not isinstance(expected, list):
                return True
            return actual not in expected
        if operator == "contains":
            if actual is None:
                return False
            if isinstance(actual, list):
                return expected in actual
            return str(expected) in str(actual)
        if operator == "exists":
            return actual is not None and actual != "" and actual != {} and actual != []
    except Exception:
        logger.warning("n8n_condition_eval_error", field=field, operator=operator)
        return False

    logger.warning("n8n_unknown_operator", operator=operator, field=field)
    return False


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

_SECTION_KEYS = frozenset({"call", "analysis", "contact", "bot_config", "transcript"})


def build_payload(
    automation: dict,
    call_data: dict | None,
    analysis: dict | None,
    contact: dict | None,
    bot_config_data: dict | None,
    transcript: list[dict] | None = None,
) -> dict:
    """Build the webhook payload based on the automation's payload_sections config."""
    sections = set(automation.get("payload_sections") or [])
    payload: dict[str, Any] = {
        "event": automation.get("timing", "unknown"),
        "automation_id": automation.get("id"),
        "automation_name": automation.get("name", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wavelength_version": "v3",
    }

    if "call" in sections and call_data:
        payload["call"] = {
            "call_sid": call_data.get("call_sid"),
            "call_duration": call_data.get("call_duration"),
            "outcome": call_data.get("outcome"),
            "recording_url": call_data.get("recording_url"),
            "started_at": call_data.get("started_at"),
            "ended_at": call_data.get("ended_at"),
        }

    if "analysis" in sections and analysis:
        payload["analysis"] = {
            "summary": analysis.get("summary"),
            "sentiment": analysis.get("sentiment"),
            "sentiment_score": analysis.get("sentiment_score"),
            "lead_temperature": analysis.get("lead_temperature"),
            "goal_outcome": analysis.get("goal_outcome"),
            "interest_level": analysis.get("interest_level"),
            "captured_data": analysis.get("captured_data"),
            "red_flags": analysis.get("red_flags"),
            "objections": analysis.get("objections"),
            "buying_signals": analysis.get("buying_signals"),
        }

    if "contact" in sections and contact:
        payload["contact"] = {
            "contact_name": contact.get("contact_name"),
            "contact_phone": contact.get("contact_phone"),
            "ghl_contact_id": contact.get("ghl_contact_id"),
            "lead_id": contact.get("lead_id"),
        }

    if "bot_config" in sections and bot_config_data:
        payload["bot_config"] = {
            "agent_name": bot_config_data.get("agent_name"),
            "company_name": bot_config_data.get("company_name"),
            "context_variables": bot_config_data.get("context_variables"),
            "goal_config": bot_config_data.get("goal_config"),
            "language": bot_config_data.get("language"),
        }

    if automation.get("include_transcript") and transcript:
        payload["transcript"] = transcript

    # Merge custom fields at top level (don't clobber existing keys)
    custom_fields = automation.get("custom_fields") or {}
    for key, value in custom_fields.items():
        if key not in payload:
            payload[key] = value

    return payload


# ---------------------------------------------------------------------------
# Webhook sender with retry
# ---------------------------------------------------------------------------


async def _send_webhook(
    url: str,
    payload: dict,
    automation_id: str,
    max_retries: int = 2,
) -> bool:
    """POST payload to webhook URL with retry on server errors.

    Retries on 5xx, 429, and network errors. No retry on 4xx client errors.
    Returns True if any attempt succeeds.
    """
    timeout = aiohttp.ClientTimeout(total=15)
    for attempt in range(1 + max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    data=_json_serialize(payload),
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status < 400:
                        logger.info(
                            "n8n_webhook_sent",
                            automation_id=automation_id,
                            status=resp.status,
                            attempt=attempt + 1,
                        )
                        return True
                    # Retry on server errors and rate limits
                    if resp.status >= 500 or resp.status == 429:
                        body = await resp.text()
                        logger.warning(
                            "n8n_webhook_server_error",
                            automation_id=automation_id,
                            status=resp.status,
                            body=body[:200],
                            attempt=attempt + 1,
                        )
                    else:
                        # 4xx client error — don't retry
                        body = await resp.text()
                        logger.error(
                            "n8n_webhook_client_error",
                            automation_id=automation_id,
                            status=resp.status,
                            body=body[:200],
                        )
                        return False
        except Exception as e:
            logger.error(
                "n8n_webhook_network_error",
                automation_id=automation_id,
                error=str(e),
                attempt=attempt + 1,
            )
        if attempt < max_retries:
            await asyncio.sleep(1.0 * (attempt + 1))  # 1s, 2s backoff
    return False


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def _extract_bot_config_data(bot_config: Any) -> dict:
    """Extract relevant fields from bot_config ORM object for payload."""
    return {
        "agent_name": getattr(bot_config, "agent_name", None),
        "company_name": getattr(bot_config, "company_name", None),
        "context_variables": getattr(bot_config, "context_variables", None),
        "goal_config": getattr(bot_config, "goal_config", None),
        "language": getattr(bot_config, "language", None),
    }


async def fire_n8n_automations(
    timing: str,
    bot_config: Any,
    call_data: dict,
    analysis: dict | None = None,
    contact: dict | None = None,
    transcript: list[dict] | None = None,
) -> None:
    """Fire all matching n8n automations for the given timing.

    This function never raises — all errors are caught and logged.
    Safe to call via asyncio.create_task() for fire-and-forget.
    """
    try:
        automations = getattr(bot_config, "n8n_automations", None) or []
        if isinstance(automations, str):
            try:
                automations = json.loads(automations)
            except (json.JSONDecodeError, TypeError):
                logger.warning("n8n_automations_json_parse_error", timing=timing)
                return
        if not isinstance(automations, list):
            logger.warning("n8n_automations_invalid_type", type=type(automations).__name__, timing=timing)
            return

        bot_id = getattr(bot_config, "id", "unknown")
        if not automations:
            logger.info("n8n_no_automations_configured", bot_id=str(bot_id), timing=timing)
            return

        logger.info(
            "n8n_fire_automations_start",
            bot_id=str(bot_id),
            timing=timing,
            automation_count=len(automations),
            call_sid=call_data.get("call_sid"),
        )

        bot_config_data = _extract_bot_config_data(bot_config)

        # Build combined call_data + analysis dict for condition evaluation
        eval_data = dict(call_data)
        if analysis:
            eval_data.update(analysis)

        tasks = []
        for auto in automations:
            if not isinstance(auto, dict):
                continue
            auto_id = auto.get("id", "unknown")
            auto_name = auto.get("name", "unnamed")

            if auto.get("timing") != timing:
                logger.debug("n8n_automation_timing_skip", automation_id=auto_id, expected=timing, actual=auto.get("timing"))
                continue
            if not auto.get("enabled", True):
                logger.info("n8n_automation_disabled", automation_id=auto_id, automation_name=auto_name)
                continue
            if not auto.get("webhook_url"):
                logger.warning("n8n_automation_missing_url", automation_id=auto_id)
                continue

            # Evaluate conditions (only meaningful for post_call with analysis data)
            conditions = auto.get("conditions", [])
            condition_logic = auto.get("condition_logic", "all")
            if timing == "post_call" and conditions and not evaluate_conditions(conditions, condition_logic, eval_data):
                logger.info(
                    "n8n_conditions_not_met",
                    automation_id=auto_id,
                    automation_name=auto_name,
                    conditions=conditions,
                    eval_data_keys=list(eval_data.keys()),
                    goal_outcome=eval_data.get("goal_outcome"),
                )
                continue

            logger.info(
                "n8n_automation_firing",
                automation_id=auto_id,
                automation_name=auto_name,
                webhook_url=auto["webhook_url"][:60],
                contact_name=contact.get("contact_name") if contact else None,
            )

            payload = build_payload(
                automation=auto,
                call_data=call_data,
                analysis=analysis,
                contact=contact,
                bot_config_data=bot_config_data,
                transcript=transcript,
            )
            tasks.append(_send_webhook(auto["webhook_url"], payload, auto_id))

        if not tasks:
            logger.info("n8n_no_automations_matched", bot_id=str(bot_id), timing=timing)
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("n8n_webhook_task_exception", error=str(result), task_index=i)

    except Exception as e:
        logger.error("n8n_fire_automations_error", error=str(e), timing=timing)
