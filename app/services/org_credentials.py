"""Utility to enrich bot_config with org-level credentials.

After loading a BotConfig, call `enrich_with_org_creds()` to fill in
telephony and GHL credentials from the organization record.
Org-level credentials always take priority — bot-level fields are ignored.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


async def enrich_with_org_creds(db: AsyncSession, bot_config) -> None:
    """Mutate bot_config in-place with org-level credentials (always override)."""
    org_result = await db.execute(
        select(Organization).where(Organization.id == bot_config.org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        return

    # GHL credentials — always from org (account-wide)
    if org.ghl_api_key:
        bot_config.ghl_api_key = org.ghl_api_key
    if org.ghl_location_id:
        bot_config.ghl_location_id = org.ghl_location_id

    # Telephony credentials — always from org (account-wide)
    if org.plivo_auth_id:
        bot_config.plivo_auth_id = org.plivo_auth_id
    if org.plivo_auth_token:
        bot_config.plivo_auth_token = org.plivo_auth_token
    if org.twilio_account_sid:
        bot_config.twilio_account_sid = org.twilio_account_sid
    if org.twilio_auth_token:
        bot_config.twilio_auth_token = org.twilio_auth_token
