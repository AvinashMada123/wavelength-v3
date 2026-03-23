"""Persistent per-lead rate limiting for sequence/flow actions.

Replaces the in-memory phone-spacing dict in sequence_scheduler.py.
Uses a lightweight SQL query against a contact log to enforce caps.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Defaults — can be overridden by org settings
DEFAULT_DAILY_CAP = 5
DEFAULT_HOURLY_CAP = 2
DEFAULT_COOLDOWN_SECONDS = 60


class RateLimiter:
    def __init__(
        self,
        db,
        daily_cap: int = DEFAULT_DAILY_CAP,
        hourly_cap: int = DEFAULT_HOURLY_CAP,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self.db = db
        self.daily_cap = daily_cap
        self.hourly_cap = hourly_cap
        self.cooldown_seconds = cooldown_seconds

    async def can_contact(self, lead_id: str, org_id: str) -> bool:
        """Check if we can contact this lead right now.

        Checks daily cap, hourly cap, and cooldown period.
        Returns True if all caps are within limits.
        """
        now = datetime.utcnow()

        # Check daily cap
        daily_count = await self._count_contacts(
            lead_id, org_id, since=now - timedelta(days=1)
        )
        if daily_count >= self.daily_cap:
            logger.debug(f"Lead {lead_id} hit daily cap ({daily_count}/{self.daily_cap})")
            return False

        # Check hourly cap
        hourly_count = await self._count_contacts(
            lead_id, org_id, since=now - timedelta(hours=1)
        )
        if hourly_count >= self.hourly_cap:
            logger.debug(f"Lead {lead_id} hit hourly cap ({hourly_count}/{self.hourly_cap})")
            return False

        # Check cooldown
        last_contact = await self._last_contact_time(lead_id, org_id)
        if last_contact and (now - last_contact).total_seconds() < self.cooldown_seconds:
            logger.debug(f"Lead {lead_id} in cooldown period")
            return False

        return True

    async def record_contact(
        self, lead_id: str, org_id: str, channel: str
    ) -> None:
        """Record that we contacted a lead. Called after successful send."""
        await self.db.execute(
            text(
                "INSERT INTO lead_contact_log (lead_id, org_id, channel, contacted_at) "
                "VALUES (:lead_id, :org_id, :channel, :contacted_at)"
            ),
            {
                "lead_id": lead_id,
                "org_id": org_id,
                "channel": channel,
                "contacted_at": datetime.utcnow(),
            },
        )
        await self.db.commit()

    async def _count_contacts(
        self, lead_id: str, org_id: str, since: datetime
    ) -> int:
        result = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM lead_contact_log "
                "WHERE lead_id = :lead_id AND org_id = :org_id AND contacted_at >= :since"
            ),
            {"lead_id": lead_id, "org_id": org_id, "since": since},
        )
        return result.scalar() or 0

    async def _last_contact_time(
        self, lead_id: str, org_id: str
    ) -> datetime | None:
        result = await self.db.execute(
            text(
                "SELECT MAX(contacted_at) FROM lead_contact_log "
                "WHERE lead_id = :lead_id AND org_id = :org_id"
            ),
            {"lead_id": lead_id, "org_id": org_id},
        )
        return result.scalar()
