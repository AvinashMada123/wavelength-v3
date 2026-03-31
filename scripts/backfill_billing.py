"""Backfill missed billing transactions for March 24-30, 2026.

Billing was broken because provider_status "picked_up" wasn't accepted.
This script finds all completed calls with duration > 0 that have no
corresponding credit_transaction, and creates them.

Run inside Docker:
  sudo docker compose exec backend python3 scripts/backfill_billing.py

DRY RUN first (default):
  python3 scripts/backfill_billing.py

LIVE RUN:
  python3 scripts/backfill_billing.py --commit
"""

import asyncio
import sys
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.billing import CreditTransaction
from app.models.call_log import CallLog
from app.models.organization import Organization

PER_MINUTE_RATE = Decimal("1.00")
SECONDS_PER_MINUTE = Decimal("60")
CENT_PRECISION = Decimal("0.01")


def calculate_credits(duration_seconds: int) -> Decimal:
    return (
        Decimal(duration_seconds) * PER_MINUTE_RATE / SECONDS_PER_MINUTE
    ).quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)


async def backfill(commit: bool = False):
    async with get_db_session() as db:
        # Find all completed calls from March 24-30 with duration > 0
        # that don't have a billing transaction
        result = await db.execute(text("""
            SELECT cl.id, cl.org_id, cl.call_sid, cl.contact_name,
                   cl.call_duration,
                   (cl.metadata->'call_metrics'->>'total_duration_s')::int as metric_duration
            FROM call_logs cl
            WHERE cl.status = 'completed'
              AND cl.created_at >= '2026-03-24'::date
              AND cl.created_at < '2026-03-31'::date
              AND (cl.call_duration > 0 OR (cl.metadata->'call_metrics'->>'total_duration_s')::int > 0)
              AND NOT EXISTS (
                  SELECT 1 FROM credit_transactions ct
                  WHERE ct.reference_id = cl.id::text
                    AND ct.type = 'usage'
              )
            ORDER BY cl.created_at
        """))
        rows = result.fetchall()

        print(f"Found {len(rows)} unbilled calls")

        total_credits = Decimal("0.00")
        org_totals: dict[str, Decimal] = {}

        for row in rows:
            call_id, org_id, call_sid, contact_name, call_duration, metric_duration = row
            duration = call_duration or metric_duration or 0
            if duration <= 0:
                continue

            credits = calculate_credits(duration)
            total_credits += credits
            org_key = str(org_id)
            org_totals[org_key] = org_totals.get(org_key, Decimal("0.00")) + credits

            print(f"  {call_sid[:12]}  {contact_name:20s}  dur={duration:4d}s  credits={credits}")

        print(f"\nTotal: {len(rows)} calls, {total_credits} credits")
        print(f"By org:")
        for org_id, total in org_totals.items():
            print(f"  {org_id}: {total} credits")

        if not commit:
            print("\n*** DRY RUN — no changes made. Pass --commit to apply. ***")
            return

        # Apply billing
        print("\nApplying billing...")
        billed = 0
        for row in rows:
            call_id, org_id, call_sid, contact_name, call_duration, metric_duration = row
            duration = call_duration or metric_duration or 0
            if duration <= 0:
                continue

            credits = calculate_credits(duration)

            # Get org and lock
            org_result = await db.execute(
                select(Organization)
                .where(Organization.id == org_id)
                .with_for_update()
            )
            org = org_result.scalar_one_or_none()
            if not org:
                print(f"  SKIP {call_sid[:12]} — org not found")
                continue

            new_balance = org.credit_balance - credits
            org.credit_balance = new_balance

            tx = CreditTransaction(
                org_id=org_id,
                amount=-credits,
                balance_after=new_balance,
                type="usage",
                description=f"Call with {contact_name} - {credits} credits for {duration}s (backfill)",
                reference_id=str(call_id),
            )
            db.add(tx)
            billed += 1

            # Commit in batches of 100 to avoid long transactions
            if billed % 100 == 0:
                await db.commit()
                print(f"  Committed {billed} so far...")

        await db.commit()
        print(f"\nDone. Billed {billed} calls, {total_credits} credits total.")


if __name__ == "__main__":
    commit = "--commit" in sys.argv
    asyncio.run(backfill(commit=commit))
