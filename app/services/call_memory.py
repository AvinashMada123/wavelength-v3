"""Fetch past call summaries to inject into the AI prompt as conversation memory."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_log import CallLog

logger = structlog.get_logger(__name__)


async def build_call_memory_prompt(
    db: AsyncSession,
    org_id,
    contact_phone: str,
    max_calls: int = 3,
) -> str | None:
    """Query past completed calls for this contact and return a formatted prompt section.

    Returns None if no previous calls exist.
    """
    result = await db.execute(
        select(CallLog)
        .where(
            CallLog.org_id == org_id,
            CallLog.contact_phone == contact_phone,
            CallLog.status == "completed",
            CallLog.summary.isnot(None),
        )
        .order_by(CallLog.created_at.desc())
        .limit(max_calls)
    )
    past_calls = result.scalars().all()

    if not past_calls:
        return None

    # Build the memory section — oldest first for chronological reading
    past_calls.reverse()

    lines = [
        "",
        "--------------------------------------------------------------------------------",
        "PREVIOUS CALL HISTORY WITH THIS CONTACT",
        "--------------------------------------------------------------------------------",
        "",
        f"You have spoken to this person {len(past_calls)} time(s) before.",
        "Use this context to personalize the conversation — reference past discussions",
        "naturally, don't repeat questions they've already answered, and build on",
        "prior rapport. Do NOT read this section out loud or mention that you have notes.",
        "",
    ]

    for i, call in enumerate(past_calls, 1):
        meta = call.metadata_ or {}
        date_str = call.created_at.strftime("%B %d, %Y") if call.created_at else "Unknown date"
        duration_str = f"{call.call_duration}s" if call.call_duration else "Unknown"
        outcome = meta.get("goal_outcome", call.outcome or "N/A")
        interest = meta.get("interest_level") or meta.get("lead_temperature") or "N/A"
        sentiment = meta.get("sentiment", "N/A")

        lines.append(f"--- Call {i} ({date_str}, Duration: {duration_str}) ---")
        lines.append(f"Outcome: {outcome}")
        lines.append(f"Interest Level: {interest}")
        lines.append(f"Sentiment: {sentiment}")
        lines.append(f"Summary: {call.summary}")

        # Include captured data if available
        captured = meta.get("captured_data")
        if captured:
            items = [f"  - {k}: {v}" for k, v in captured.items() if v]
            if items:
                lines.append("Captured Data:")
                lines.extend(items)

        lines.append("")

    lines.append("--------------------------------------------------------------------------------")
    lines.append("")

    logger.info(
        "call_memory_built",
        org_id=str(org_id),
        phone=contact_phone,
        past_calls=len(past_calls),
    )

    return "\n".join(lines)
