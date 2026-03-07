"""GoHighLevel REST API client for contact data and call outcome webhooks."""

from __future__ import annotations

import asyncio

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

    async def find_contact(self, location_id: str, phone: str) -> str | None:
        """Search for a GHL contact by phone number. Returns contact ID or None."""
        clean_phone = phone.strip()
        if not clean_phone.startswith("+"):
            clean_phone = "+" + clean_phone

        session = await self._get_session()
        url = f"{GHL_BASE_URL}/contacts/"
        try:
            async with session.get(url, params={"locationId": location_id, "query": clean_phone}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    contacts = data.get("contacts", [])
                    if contacts:
                        contact_id = contacts[0].get("id")
                        logger.info("ghl_contact_found", phone=clean_phone, contact_id=contact_id)
                        return contact_id
                else:
                    logger.warning("ghl_find_contact_failed", status=resp.status, phone=clean_phone)
        except Exception as e:
            logger.error("ghl_find_contact_error", error=str(e), phone=clean_phone)
        return None

    async def tag_contact(self, contact_id: str, tag: str) -> bool:
        """Add a tag to a GHL contact."""
        session = await self._get_session()
        url = f"{GHL_BASE_URL}/contacts/{contact_id}/tags"
        try:
            async with session.post(url, json={"tags": [tag]}) as resp:
                if resp.status < 400:
                    logger.info("ghl_tag_added", contact_id=contact_id, tag=tag)
                    return True
                body = await resp.text()
                logger.error("ghl_tag_failed", status=resp.status, body=body[:200])
                return False
        except Exception as e:
            logger.error("ghl_tag_error", error=str(e), contact_id=contact_id, tag=tag)
            return False

    async def post_call_outcome(self, webhook_url: str, outcome_data: dict, max_retries: int = 2) -> bool:
        """POST call outcome to bot's configured GHL webhook URL with retry."""
        session = await self._get_session()
        for attempt in range(1 + max_retries):
            try:
                async with session.post(webhook_url, json=outcome_data) as resp:
                    if resp.status < 400:
                        return True
                    body = await resp.text()
                    logger.error("ghl_webhook_post_failed", status=resp.status, body=body[:200], attempt=attempt + 1)
            except Exception as e:
                logger.error("ghl_webhook_post_error", error=str(e), webhook_url=webhook_url, attempt=attempt + 1)
            if attempt < max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))  # 1s, 2s backoff
        return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
