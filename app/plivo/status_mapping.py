"""Plivo call status mapping — pure functions with no heavy imports.

Extracted from routes.py so they can be tested without pulling in pipecat.
"""
from datetime import datetime, timezone

from sqlalchemy import select

import structlog

logger = structlog.get_logger(__name__)

# Maps raw Plivo CallStatus to normalized CallOutcome enum values.
# IMPORTANT: Do NOT collapse statuses — each value is used for flow branching.
PLIVO_STATUS_MAP = {
    "completed": "picked_up",
    "busy": "busy",
    "failed": "failed",
    "timeout": "timeout",
    "no-answer": "no_answer",
    "cancel": "failed",
    "machine": "voicemail",
}


def _map_plivo_status(plivo_status: str | None) -> str:
    """Map raw Plivo status to normalized CallOutcome.

    Returns the normalized status for flow condition branching.
    Unknown statuses return 'unknown' rather than passing through raw values.
    """
    if plivo_status is None:
        return "unknown"
    return PLIVO_STATUS_MAP.get(plivo_status, "unknown")


async def _update_sequence_touchpoint(
    db,
    touchpoint_id: str,
    call_outcome: str,
    raw_plivo_status: str,
) -> None:
    """Update a sequence touchpoint with the call outcome.

    Called from plivo_event() when a call finishes and the CallLog
    has a sequence_touchpoint_id in context_data.
    """
    from app.models.sequence import SequenceTouchpoint

    result = await db.execute(
        select(SequenceTouchpoint).where(SequenceTouchpoint.id == touchpoint_id)
    )
    touchpoint = result.scalars().first()

    if not touchpoint:
        logger.warning("touchpoint_not_found_for_outcome", touchpoint_id=touchpoint_id)
        return

    if touchpoint.status not in ("scheduled", "sending"):
        logger.info("touchpoint_already_terminal", touchpoint_id=touchpoint_id, status=touchpoint.status)
        return

    touchpoint.status = "sent" if call_outcome == "picked_up" else "failed"
    touchpoint.sent_at = datetime.now(timezone.utc)

    snapshot = touchpoint.step_snapshot or {}
    snapshot["call_outcome"] = call_outcome
    snapshot["raw_plivo_status"] = raw_plivo_status
    touchpoint.step_snapshot = snapshot

    await db.commit()
    logger.info("touchpoint_outcome_updated", touchpoint_id=touchpoint_id, call_outcome=call_outcome)
