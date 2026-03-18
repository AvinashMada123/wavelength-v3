"""Multi-provider messaging client for WhatsApp and SMS delivery."""

import aiohttp
import structlog

from app.services.credential_encryption import decrypt_credentials
from app.config import settings

logger = structlog.get_logger(__name__)


class DeliveryResult:
    """Standardized delivery result across all providers."""

    def __init__(self, success: bool, message_id: str | None = None, error: str | None = None):
        self.success = success
        self.message_id = message_id
        self.error = error

    def to_dict(self):
        return {"success": self.success, "message_id": self.message_id, "error": self.error}


async def _get_provider_creds(encrypted_creds: str) -> dict:
    """Decrypt provider credentials."""
    return decrypt_credentials(encrypted_creds, settings.MESSAGING_CREDENTIALS_KEY)


# ---------------------------------------------------------------------------
# WATI
# ---------------------------------------------------------------------------

async def _wati_send_template(
    creds: dict, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via WATI."""
    # WATI expects phone without + prefix
    clean_phone = phone.lstrip("+")
    url = f"{creds['api_url']}/api/v1/sendTemplateMessage?whatsappNumber={clean_phone}"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {
        "template_name": template_name,
        "broadcast_name": f"seq_{template_name}_{clean_phone}",
        "parameters": params,
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId") or data.get("id"))
                return DeliveryResult(False, error=f"WATI {resp.status}: {data}")
        except Exception as e:
            logger.exception("wati_send_template_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


async def _wati_send_session(creds: dict, phone: str, text: str) -> DeliveryResult:
    """Send a WhatsApp session (free-form) message via WATI."""
    clean_phone = phone.lstrip("+")
    url = f"{creds['api_url']}/api/v1/sendSessionMessage/{clean_phone}"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {"messageText": text}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId") or data.get("id"))
                return DeliveryResult(False, error=f"WATI session {resp.status}: {data}")
        except Exception as e:
            logger.exception("wati_send_session_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


# ---------------------------------------------------------------------------
# AISensy
# ---------------------------------------------------------------------------

async def _aisensy_send_template(
    creds: dict, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via AISensy."""
    url = f"{creds['api_url']}/campaign/smart-campaign/api/v1"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    param_values = [p.get("value", "") for p in params] if params else []
    body = {
        "apiKey": creds.get("api_key", ""),
        "campaignName": f"seq_{template_name}_{phone}",
        "destination": phone,
        "userName": "Wavelength",
        "templateParams": param_values,
        "source": "wavelength-sequence",
        "media": {},
        "buttons": [],
        "carouselCards": [],
        "location": {},
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400 and data.get("result"):
                    return DeliveryResult(True, message_id=data.get("data", {}).get("messageId"))
                return DeliveryResult(False, error=f"AISensy {resp.status}: {data}")
        except Exception as e:
            logger.exception("aisensy_send_template_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


async def _aisensy_send_session(creds: dict, phone: str, text: str) -> DeliveryResult:
    """Send a session message via AISensy."""
    url = f"{creds['api_url']}/project/api/v1/sendSessionMessage/{phone}"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {"messageText": text}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId"))
                return DeliveryResult(False, error=f"AISensy session {resp.status}: {data}")
        except Exception as e:
            logger.exception("aisensy_send_session_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


# ---------------------------------------------------------------------------
# Public interface (factory pattern)
# ---------------------------------------------------------------------------

TEMPLATE_HANDLERS = {
    "wati": _wati_send_template,
    "aisensy": _aisensy_send_template,
}

SESSION_HANDLERS = {
    "wati": _wati_send_session,
    "aisensy": _aisensy_send_session,
}


async def send_template(
    encrypted_creds: str, provider_type: str, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via the appropriate provider."""
    creds = await _get_provider_creds(encrypted_creds)
    handler = TEMPLATE_HANDLERS.get(provider_type)
    if not handler:
        return DeliveryResult(False, error=f"Unsupported provider: {provider_type}")
    return await handler(creds, phone, template_name, params)


async def send_session_message(
    encrypted_creds: str, provider_type: str, phone: str, text: str
) -> DeliveryResult:
    """Send a WhatsApp session message via the appropriate provider."""
    creds = await _get_provider_creds(encrypted_creds)
    handler = SESSION_HANDLERS.get(provider_type)
    if not handler:
        return DeliveryResult(False, error=f"Unsupported provider for session: {provider_type}")
    return await handler(creds, phone, text)


async def send_sms(
    encrypted_creds: str, provider_type: str, phone: str, text: str
) -> DeliveryResult:
    """Send an SMS via the appropriate provider. Placeholder for v1."""
    logger.warning("sms_not_implemented", provider_type=provider_type, phone=phone)
    return DeliveryResult(False, error="SMS sending not yet implemented")
