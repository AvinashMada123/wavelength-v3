"""Twilio REST API client for making outbound calls."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01/Accounts"


async def make_outbound_call(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    answer_url: str,
    status_callback_url: str,
) -> str | None:
    """
    Initiate a Twilio outbound call.
    Returns the Twilio Call SID on success, or None on failure.
    """
    url = f"{TWILIO_API_BASE}/{account_sid}/Calls.json"
    payload = {
        "To": to_number,
        "From": from_number,
        "Url": answer_url,
        "StatusCallback": status_callback_url,
        "StatusCallbackMethod": "POST",
        "StatusCallbackEvent": "initiated ringing answered completed",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                auth=(account_sid, auth_token),
                data=payload,
            )
            response.raise_for_status()
            result = response.json()
            call_sid = result.get("sid", "")
            logger.info("twilio_call_initiated", to=to_number, call_sid=call_sid)
            return call_sid
    except httpx.HTTPStatusError as e:
        logger.error("twilio_call_http_error", error=str(e), body=e.response.text, to=to_number)
        return None
    except Exception as e:
        logger.error("twilio_call_failed", error=str(e), to=to_number)
        return None
