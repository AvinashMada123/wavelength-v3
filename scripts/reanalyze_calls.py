"""
Re-analyze past calls for a bot using its current goal_config.

Usage (inside Docker container):
  python -m scripts.reanalyze_calls <bot_id> [--limit N] [--dry-run]

Or from host via docker exec:
  sudo docker exec wavelength-backend python -m scripts.reanalyze_calls <bot_id> --limit 5
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.bot_config import BotConfig
from app.models.call_log import CallLog
from app.models.call_analytics import CallAnalytics
from app.models.schemas import CallAnalysis, GoalConfig
from app.services.call_analyzer import CallAnalyzer

logger = structlog.get_logger(__name__)


def _compute_agent_word_share(transcript: list[dict]) -> float:
    bot_words = sum(len(t["content"].split()) for t in transcript if t["role"] == "assistant")
    user_words = sum(len(t["content"].split()) for t in transcript if t["role"] == "user")
    total = bot_words + user_words
    return round(bot_words / total, 2) if total > 0 else 0.0


def _get_max_severity(red_flags: list[dict]) -> str | None:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    if not red_flags:
        return None
    return min(red_flags, key=lambda rf: order.get(rf.get("severity", "low"), 99)).get("severity")


async def reanalyze(bot_id: str, limit: int = 50, dry_run: bool = False):
    # Load bot config
    async with get_db_session() as db:
        result = await db.execute(
            select(BotConfig).where(BotConfig.id == bot_id)
        )
        bot = result.scalar_one_or_none()

    if not bot:
        print(f"Bot {bot_id} not found")
        return

    goal_cfg = bot.goal_config
    if isinstance(goal_cfg, str):
        goal_cfg = json.loads(goal_cfg)

    if not goal_cfg:
        print(f"Bot {bot_id} has no goal_config — nothing to analyze")
        return

    goal_type = goal_cfg.get("goal_type", "unknown")
    print(f"Bot: {bot.agent_name} ({bot.company_name})")
    print(f"Goal: {goal_type}")
    print(f"Limit: {limit} calls")
    print(f"Dry run: {dry_run}")
    print("---")

    # Fetch calls with transcripts
    async with get_db_session() as db:
        result = await db.execute(
            select(CallLog)
            .where(CallLog.bot_id == bot_id)
            .where(CallLog.status.in_(["completed", "error"]))
            .order_by(CallLog.created_at.desc())
            .limit(limit)
        )
        calls = result.scalars().all()

    print(f"Found {len(calls)} calls to analyze")

    analyzer = CallAnalyzer()
    success = 0
    skipped = 0
    errors = 0

    for call in calls:
        call_sid = call.call_sid
        meta = call.metadata_ or {}
        transcript = meta.get("transcript", [])

        if not transcript:
            print(f"  [{call_sid}] SKIP — no transcript")
            skipped += 1
            continue

        turn_count = len([t for t in transcript if t.get("role") == "user"])
        print(f"  [{call_sid}] {turn_count} user turns, {len(transcript)} messages...", end=" ")

        if dry_run:
            print("DRY RUN")
            continue

        try:
            analysis = await analyzer.analyze(
                transcript=transcript,
                goal_config=goal_cfg,
                system_prompt=bot.system_prompt_template or "",
                call_sid=call_sid,
            )

            # Check if analytics row already exists
            async with get_db_session() as db:
                existing = await db.execute(
                    select(CallAnalytics).where(CallAnalytics.call_log_id == call.id)
                )
                existing_row = existing.scalar_one_or_none()

                if existing_row:
                    # Update existing row
                    existing_row.goal_outcome = analysis.goal_outcome
                    existing_row.has_red_flags = len(analysis.red_flags) > 0
                    existing_row.red_flag_max_severity = _get_max_severity(
                        [rf.model_dump() for rf in analysis.red_flags]
                    ) if analysis.red_flags else None
                    existing_row.red_flags = [rf.model_dump() for rf in analysis.red_flags] or None
                    existing_row.captured_data = analysis.captured_data or None
                    existing_row.turn_count = turn_count
                    existing_row.agent_word_share = _compute_agent_word_share(transcript)
                else:
                    # Insert new row
                    row = CallAnalytics(
                        call_log_id=call.id,
                        bot_id=UUID(bot_id),
                        goal_type=goal_type,
                        goal_outcome=analysis.goal_outcome,
                        has_red_flags=len(analysis.red_flags) > 0,
                        red_flag_max_severity=_get_max_severity(
                            [rf.model_dump() for rf in analysis.red_flags]
                        ) if analysis.red_flags else None,
                        red_flags=[rf.model_dump() for rf in analysis.red_flags] or None,
                        captured_data=analysis.captured_data or None,
                        turn_count=turn_count,
                        call_duration_secs=call.call_duration,
                        agent_word_share=_compute_agent_word_share(transcript),
                    )
                    db.add(row)

                await db.commit()

            flags = len(analysis.red_flags)
            print(f"outcome={analysis.goal_outcome} flags={flags} summary={len(analysis.summary or '')}ch")
            success += 1

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print("---")
    print(f"Done: {success} analyzed, {skipped} skipped, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Re-analyze past calls for a bot")
    parser.add_argument("bot_id", help="Bot UUID")
    parser.add_argument("--limit", type=int, default=50, help="Max calls to analyze (default 50)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without running analysis")
    args = parser.parse_args()

    asyncio.run(reanalyze(args.bot_id, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
