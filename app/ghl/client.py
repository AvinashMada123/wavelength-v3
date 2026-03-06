"""GoHighLevel REST API client for contact data and call outcome webhooks."""

from __future__ import annotations

import aiohttp
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"


class GHLClient:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.GHL_API_KEY
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Version": "2021-07-28",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def get_contact(self, ghl_contact_id: str) -> dict | None:
        """Fetch contact from GHL. Returns contact dict with custom fields."""
        session = await self._get_session()
        url = f"{GHL_BASE_URL}/contacts/{ghl_contact_id}"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("contact")
                logger.warning("ghl_get_contact_failed", status=resp.status, contact_id=ghl_contact_id)
                return None
        except Exception as e:
            logger.error("ghl_get_contact_error", error=str(e), contact_id=ghl_contact_id)
            return None

    async def post_call_outcome(self, webhook_url: str, outcome_data: dict) -> bool:
        """POST call outcome to bot's configured GHL webhook URL."""
        session = await self._get_session()
        try:
            async with session.post(webhook_url, json=outcome_data) as resp:
                success = resp.status < 400
                if not success:
                    body = await resp.text()
                    logger.error("ghl_webhook_post_failed", status=resp.status, body=body[:200])
                return success
        except Exception as e:
            logger.error("ghl_webhook_post_error", error=str(e), webhook_url=webhook_url)
            return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
