"""Utility to enrich bot_config with org-level credentials.

After loading a BotConfig, call `enrich_with_org_creds()` to fill in
any missing telephony/GHL credentials from the organization record.
This ensures backward compatibility — bot-level creds take priority,
org-level creds fill in gaps.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


async def enrich_with_org_creds(db: AsyncSession, bot_config) -> None:
    """Mutate bot_config in-place, filling missing creds from org."""
    org_result = await db.execute(
        select(Organization).where(Organization.id == bot_config.org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        return

    # GHL credentials
    if not getattr(bot_config, "ghl_api_key", None) and org.ghl_api_key:
        bot_config.ghl_api_key = org.ghl_api_key
    if not getattr(bot_config, "ghl_location_id", None) and org.ghl_location_id:
        bot_config.ghl_location_id = org.ghl_location_id

    # Telephony credentials (for legacy code paths)
    if not getattr(bot_config, "plivo_auth_id", None) and org.plivo_auth_id:
        bot_config.plivo_auth_id = org.plivo_auth_id
    if not getattr(bot_config, "plivo_auth_token", None) and org.plivo_auth_token:
        bot_config.plivo_auth_token = org.plivo_auth_token
    if not getattr(bot_config, "twilio_account_sid", None) and org.twilio_account_sid:
        bot_config.twilio_account_sid = org.twilio_account_sid
    if not getattr(bot_config, "twilio_auth_token", None) and org.twilio_auth_token:
        bot_config.twilio_auth_token = org.twilio_auth_token
