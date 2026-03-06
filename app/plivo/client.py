"""Plivo REST API wrapper for making outbound calls."""

from __future__ import annotations

import asyncio
from functools import partial

import plivo
import structlog

logger = structlog.get_logger(__name__)


def _plivo_create_call(
    auth_id: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    answer_url: str,
    hangup_url: str,
) -> str:
    """Synchronous Plivo SDK call — runs in a thread executor."""
    client = plivo.RestClient(auth_id=auth_id, auth_token=auth_token)
    response = client.calls.create(
        from_=from_number,
        to_=to_number,
        answer_url=answer_url,
        answer_method="GET",
        hangup_url=hangup_url,
        hangup_method="POST",
    )
    return response.request_uuid if hasattr(response, "request_uuid") else str(response)


async def make_outbound_call(
    auth_id: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    answer_url: str,
    hangup_url: str,
) -> str | None:
    """
    Initiate a Plivo outbound call (async wrapper around sync SDK).
    Returns the Plivo request_uuid on success, or None on failure.
    """
    try:
        loop = asyncio.get_running_loop()
        request_uuid = await loop.run_in_executor(
            None,
            partial(
                _plivo_create_call,
                auth_id, auth_token, from_number, to_number, answer_url, hangup_url,
            ),
        )
        logger.info("plivo_call_initiated", to=to_number, request_uuid=request_uuid)
        return request_uuid
    except Exception as e:
        logger.error("plivo_call_failed", error=str(e), to=to_number)
        return None
