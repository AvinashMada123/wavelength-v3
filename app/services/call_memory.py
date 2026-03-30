"""Fetch past call context to inject into the AI prompt as conversation memory.

Queries CallLog + CallAnalytics to build a rich context block including:
- Call summaries (chronological)
- Consolidated known facts (captured data, latest wins)
- Outcome, sentiment, interest level per call
- Objection history
- Red flag warnings
- Buying signals
- Time-since-last-call framing
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_analytics import CallAnalytics
from app.models.call_log import CallLog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O, fully testable)
# ---------------------------------------------------------------------------


def _fmt_duration(secs: int | None) -> str:
    """Format seconds into human-readable duration."""
    if secs is None:
        return "Unknown"
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60}s"


def _fmt_recency(delta_days: int) -> tuple[str, str]:
    """Return (time_ago_string, behavioral_framing)."""
    if delta_days == 0:
        time_ago = "earlier today"
    elif delta_days == 1:
        time_ago = "yesterday"
    elif delta_days < 7:
        time_ago = f"{delta_days} days ago"
    elif delta_days < 30:
        weeks = delta_days // 7
        time_ago = f"about {weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        months = delta_days // 30
        time_ago = f"about {months} month{'s' if months != 1 else ''} ago"

    if delta_days <= 3:
        framing = "This is a recent follow-up. Be casual and pick up where you left off."
    elif delta_days <= 14:
        framing = "This is a follow-up from last week. Briefly reference your last conversation."
    elif delta_days <= 30:
        framing = "It has been a while. Briefly re-establish context before continuing."
    else:
        framing = "It has been over a month. Re-introduce yourself briefly but acknowledge you have spoken before."

    return time_ago, framing


def _format_memory_section(
    rows: list[tuple],
    now: datetime | None = None,
) -> str:
    """Format call history + analytics into a prompt section.

    Args:
        rows: List of (CallLog, CallAnalytics|None) tuples, oldest first.
        now: Current time (injectable for testing).

    Returns:
        Formatted prompt string, or empty string if no rows.
    """
    if not rows:
        return ""

    now = now or datetime.now(timezone.utc)

    # --- Recency from most recent call (last in chronological list) ---
    most_recent_call = rows[-1][0]
    most_recent_dt = most_recent_call.created_at
    delta_days = (now - most_recent_dt).days if most_recent_dt else 0
    time_ago, framing = _fmt_recency(delta_days)

    # --- Aggregate data across all calls ---
    consolidated_facts: dict[str, str] = {}
    all_objections: list[dict] = []
    all_red_flags: list[dict] = []
    all_buying_signals: list[str] = []
    has_negative_sentiment = False

    for call, analytics in rows:
        if not analytics:
            continue
        # Captured data — latest call's values override older ones
        if analytics.captured_data:
            consolidated_facts.update(
                {k: str(v) for k, v in analytics.captured_data.items() if v is not None}
            )
        # Objections — keep most recent call's list
        if analytics.objections:
            all_objections = analytics.objections
        # Red flags — accumulate unique across all calls
        if analytics.red_flags:
            for rf in analytics.red_flags:
                if rf not in all_red_flags:
                    all_red_flags.append(rf)
        # Buying signals — keep most recent
        if analytics.buying_signals:
            all_buying_signals = analytics.buying_signals
        # Track negative sentiment
        if analytics.sentiment and analytics.sentiment.lower() in (
            "negative",
            "very_negative",
        ):
            has_negative_sentiment = True

    # --- Build prompt ---
    lines = [
        "",
        "--------------------------------------------------------------------------------",
        "PREVIOUS CALL HISTORY WITH THIS CONTACT",
        "--------------------------------------------------------------------------------",
        "",
        f"You have spoken to this person {len(rows)} time(s) before.",
        f"Most recent call was {time_ago}. {framing}",
        "",
        "RULES:",
        "1. Do NOT repeat your full introduction. This is a follow-up.",
        "2. Only reference details explicitly provided below — never invent or assume details not shown.",
    ]

    if consolidated_facts:
        lines.append(
            "3. Do NOT re-ask questions if the answer is already in KNOWN FACTS below."
        )

    if has_negative_sentiment:
        lines.append(
            "4. Previous calls had negative sentiment. Open cautiously and gently "
            "acknowledge any past frustration."
        )

    lines.append("")

    # --- Consolidated known facts ---
    if consolidated_facts:
        lines.append("KNOWN FACTS (from previous calls — do NOT re-ask these):")
        for key, value in consolidated_facts.items():
            label = key.replace("_", " ").title()
            lines.append(f"  - {label}: {value}")
        lines.append("")

    # --- Per-call details ---
    for i, (call, analytics) in enumerate(rows, 1):
        date_str = (
            call.created_at.strftime("%B %d, %Y") if call.created_at else "Unknown date"
        )
        duration_str = _fmt_duration(call.call_duration)

        # Outcome: prefer analytics, fall back to CallLog
        outcome = None
        if analytics and analytics.goal_outcome:
            outcome = analytics.goal_outcome
        elif call.outcome:
            outcome = call.outcome

        # Sentiment & interest
        sentiment = analytics.sentiment if analytics and analytics.sentiment else None
        interest = (
            analytics.lead_temperature if analytics and analytics.lead_temperature else None
        )

        # Header
        lines.append(f"--- Call {i} ({date_str}, Duration: {duration_str}) ---")

        # Structured metadata line
        meta_parts: list[str] = []
        if outcome:
            meta_parts.append(f"Outcome: {outcome}")
        if sentiment:
            meta_parts.append(f"Sentiment: {sentiment}")
        if interest:
            meta_parts.append(f"Interest: {interest}")
        if meta_parts:
            lines.append(" | ".join(meta_parts))

        # Flag very short calls
        if call.call_duration is not None and call.call_duration < 30:
            lines.append(
                "(This was a very brief call — likely no substantive conversation.)"
            )

        # Summary
        lines.append(call.summary or "No summary available.")
        lines.append("")

    # --- Objections ---
    if all_objections:
        lines.append("OBJECTIONS RAISED IN PREVIOUS CALLS:")
        for obj in all_objections:
            text = obj.get("text", obj.get("category", "Unknown"))
            resolved = obj.get("resolved", False)
            status = "resolved" if resolved else "unresolved"
            lines.append(f'  - "{text}" ({status})')
        lines.append("")

    # --- Buying signals ---
    if all_buying_signals:
        lines.append("BUYING SIGNALS DETECTED:")
        for signal in all_buying_signals:
            lines.append(f"  - {signal}")
        lines.append("")

    # --- Red flags ---
    if all_red_flags:
        lines.append("RED FLAGS FROM PREVIOUS CALLS:")
        for rf in all_red_flags:
            flag_id = rf.get("id", "unknown")
            severity = rf.get("severity", "unknown")
            lines.append(f"  - {flag_id} (severity: {severity})")
        lines.append("")

    lines.append("--------------------------------------------------------------------------------")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async DB function
# ---------------------------------------------------------------------------


async def build_call_memory_prompt(
    db: AsyncSession,
    org_id,
    contact_phone: str,
    max_calls: int = 3,
) -> str | None:
    """Query past completed calls + analytics for this contact.

    Returns a formatted prompt section, or None if no previous calls exist.
    """
    stmt = (
        select(CallLog, CallAnalytics)
        .outerjoin(CallAnalytics, CallAnalytics.call_log_id == CallLog.id)
        .where(
            CallLog.org_id == org_id,
            CallLog.contact_phone == contact_phone,
            CallLog.status == "completed",
            CallLog.summary.isnot(None),
        )
        .order_by(CallLog.created_at.desc())
        .limit(max_calls)
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return None

    # Oldest first for chronological reading
    rows_list = list(rows)
    rows_list.reverse()

    prompt = _format_memory_section(rows_list, now=datetime.now(timezone.utc))

    logger.info(
        "call_memory_built",
        org_id=str(org_id),
        phone=contact_phone,
        past_calls=len(rows_list),
    )

    return prompt
