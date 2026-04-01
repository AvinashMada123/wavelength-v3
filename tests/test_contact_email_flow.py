"""Tests for contact_email field flowing through the entire pipeline.

Chain: Webhook/API → QueuedCall → CallLog → CallContext → n8n payload

These tests are written BEFORE implementation to drive the changes (TDD).
"""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock structlog before importing modules under test
sys.modules.setdefault(
    "structlog",
    SimpleNamespace(
        get_logger=lambda *a, **kw: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
    ),
)


# ---------------------------------------------------------------------------
# 1. Webhook payload extraction — contactEmail from GHL
# ---------------------------------------------------------------------------


class TestWebhookEmailExtraction:
    """Verify that contactEmail is extracted from GHL webhook payloads."""

    def _parse_ghl_payload(self, body: dict):
        """Simulate the webhook parsing logic."""
        from app.api.webhook import _parse_webhook_payload
        return _parse_webhook_payload(body)

    def test_ghl_payload_extracts_contact_email(self):
        """contactEmail from GHL customData should be captured."""
        body = {
            "customData": {
                "phoneNumber": "+919609775259",
                "contactName": "Animesh",
                "botConfigId": "958d1ffb-eefb-4a6d-8540-476486cc66f8",
                "contactEmail": "animesh@example.com",
                "cvAgent_name": "Sneha",
            },
            "contact_id": "ghl-123",
        }
        result = self._parse_ghl_payload(body)
        assert result["contact_email"] == "animesh@example.com"

    def test_ghl_payload_email_none_when_missing(self):
        """Missing contactEmail should result in None, not error."""
        body = {
            "customData": {
                "phoneNumber": "+919609775259",
                "contactName": "Animesh",
                "botConfigId": "958d1ffb-eefb-4a6d-8540-476486cc66f8",
            },
            "contact_id": "ghl-123",
        }
        result = self._parse_ghl_payload(body)
        assert result["contact_email"] is None

    def test_standard_payload_extracts_contact_email(self):
        """Standard (non-GHL) payload should also support contactEmail."""
        body = {
            "phoneNumber": "+919609775259",
            "contactName": "Animesh",
            "botConfigId": "958d1ffb-eefb-4a6d-8540-476486cc66f8",
            "contactEmail": "animesh@example.com",
        }
        result = self._parse_ghl_payload(body)
        assert result["contact_email"] == "animesh@example.com"

    def test_top_level_email_fallback(self):
        """GHL payload with email at top level should be used as fallback."""
        body = {
            "customData": {
                "phoneNumber": "+919609775259",
                "contactName": "Animesh",
                "botConfigId": "958d1ffb-eefb-4a6d-8540-476486cc66f8",
            },
            "contact_id": "ghl-123",
            "email": "fallback@example.com",
        }
        result = self._parse_ghl_payload(body)
        assert result["contact_email"] == "fallback@example.com"


# ---------------------------------------------------------------------------
# 2. QueuedCall model — contact_email column
# ---------------------------------------------------------------------------


class TestQueuedCallEmail:
    """Verify QueuedCall model has contact_email field."""

    def test_queued_call_has_email_field(self):
        from app.models.call_queue import QueuedCall
        assert hasattr(QueuedCall, "contact_email"), \
            "QueuedCall must have a contact_email column"

    def test_queued_call_email_is_nullable(self):
        """contact_email should be optional (nullable)."""
        from app.models.call_queue import QueuedCall
        col = QueuedCall.__table__.columns["contact_email"]
        assert col.nullable is True


# ---------------------------------------------------------------------------
# 3. CallLog model — contact_email column
# ---------------------------------------------------------------------------


class TestCallLogEmail:
    """Verify CallLog model has contact_email field."""

    def test_call_log_has_email_field(self):
        from app.models.call_log import CallLog
        assert hasattr(CallLog, "contact_email"), \
            "CallLog must have a contact_email column"

    def test_call_log_email_is_nullable(self):
        from app.models.call_log import CallLog
        col = CallLog.__table__.columns["contact_email"]
        assert col.nullable is True


# ---------------------------------------------------------------------------
# 4. CallContext — contact_email attribute
# ---------------------------------------------------------------------------


class TestCallContextEmail:
    """Verify CallContext carries contact_email."""

    def test_call_context_accepts_email(self):
        """CallContext constructor should accept contact_email parameter."""
        from app.models.schemas import CallContext
        ctx = CallContext(
            call_sid="test-sid",
            filled_prompt="test prompt",
            contact_name="Animesh",
            ghl_contact_id=None,
            ghl_webhook_url=None,
            tts_provider="gemini",
            tts_voice="Kore",
            tts_style_prompt=None,
            language="en-IN",
            silence_timeout_secs=15,
            bot_id="bot-123",
            contact_email="animesh@example.com",
        )
        assert ctx.contact_email == "animesh@example.com"

    def test_call_context_email_defaults_none(self):
        """contact_email should default to None if not provided."""
        from app.models.schemas import CallContext
        ctx = CallContext(
            call_sid="test-sid",
            filled_prompt="test prompt",
            contact_name="Animesh",
            ghl_contact_id=None,
            ghl_webhook_url=None,
            tts_provider="gemini",
            tts_voice="Kore",
            tts_style_prompt=None,
            language="en-IN",
            silence_timeout_secs=15,
            bot_id="bot-123",
        )
        assert ctx.contact_email is None

    def test_call_context_from_db_reads_email(self):
        """from_db should extract contact_email from context_data."""
        from app.models.schemas import CallContext

        mock_log = SimpleNamespace(
            call_sid="test-sid",
            bot_id="bot-123",
            contact_name="Animesh",
            contact_phone="+919609775259",
            contact_email="animesh@example.com",
            ghl_contact_id=None,
            context_data={
                "contact_name": "Animesh",
                "contact_email": "animesh@example.com",
                "ghl_contact_id": None,
                "filled_prompt": "test",
                "ghl_webhook_url": None,
                "tts_provider": "gemini",
                "tts_voice": "Kore",
                "tts_style_prompt": None,
                "language": "en-IN",
                "silence_timeout_secs": 15,
                "bot_id": "bot-123",
            },
        )

        ctx = CallContext.from_db(mock_log)
        assert ctx.contact_email == "animesh@example.com"


# ---------------------------------------------------------------------------
# 5. n8n webhook payload — contact.contact_email
# ---------------------------------------------------------------------------


class TestN8nPayloadEmail:
    """Verify contact_email appears in n8n webhook payload."""

    def test_build_payload_includes_email(self):
        from app.services.n8n_webhook import build_payload

        auto = {
            "id": "auto-001",
            "name": "Test",
            "timing": "post_call",
            "payload_sections": ["contact"],
        }
        contact = {
            "contact_name": "Animesh",
            "contact_phone": "+919609775259",
            "ghl_contact_id": None,
            "contact_email": "animesh@example.com",
        }
        result = build_payload(auto, None, None, contact, None)
        assert result["contact"]["contact_email"] == "animesh@example.com"

    def test_build_payload_email_none_still_present(self):
        """Even when email is None, the field should be in the payload."""
        from app.services.n8n_webhook import build_payload

        auto = {
            "id": "auto-001",
            "name": "Test",
            "timing": "post_call",
            "payload_sections": ["contact"],
        }
        contact = {
            "contact_name": "Animesh",
            "contact_phone": "+919609775259",
            "ghl_contact_id": None,
            "contact_email": None,
        }
        result = build_payload(auto, None, None, contact, None)
        assert "contact_email" in result["contact"]
        assert result["contact"]["contact_email"] is None


# ---------------------------------------------------------------------------
# 6. API endpoints — TriggerCallRequest and EnqueueCallRequest
# ---------------------------------------------------------------------------


class TestApiRequestSchemas:
    """Verify API request schemas accept contact_email."""

    def test_trigger_call_request_accepts_email(self):
        from app.models.schemas import TriggerCallRequest

        req = TriggerCallRequest(
            bot_id=uuid.uuid4(),
            contact_name="Animesh",
            contact_phone="+919609775259",
            contact_email="animesh@example.com",
        )
        assert req.contact_email == "animesh@example.com"

    def test_trigger_call_request_email_optional(self):
        from app.models.schemas import TriggerCallRequest

        req = TriggerCallRequest(
            bot_id=uuid.uuid4(),
            contact_name="Animesh",
            contact_phone="+919609775259",
        )
        assert req.contact_email is None
