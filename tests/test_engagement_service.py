"""Unit tests for engagement_service — mocked DB, no real database."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

from app.services.engagement_service import (
    create_engagement,
    update_touchpoint,
    update_report_link,
    get_engagement,
)

_ORG_ID = uuid.uuid4()
_CALL_LOG_ID = uuid.uuid4()
_PHONE = "+919609775259"
_EMAIL = "test@example.com"
_EXTRACTION = {
    "profession_spoken": "software engineer",
    "pain_or_goal": "wants to automate test cases",
    "specific_task": "test cases",
    "energy_level": "high",
    "confirmed_saturday": "yes",
    "personalized_hook": "When Avinash sir builds an app...",
    "gift_plan": "1. Auto-generate test cases\n2. AI code review\n3. Automated docs\nAnd that's just the summary.",
}


def _mock_db(scalar_result=None, scalar_one_result=None):
    """Create a mock AsyncSession."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_result
    result_mock.scalar.return_value = scalar_one_result
    db.execute.return_value = result_mock
    return db


class TestCreateEngagement:
    @pytest.mark.asyncio
    async def test_creates_with_valid_data(self):
        db = _mock_db()
        result = await create_engagement(
            db=db,
            org_id=_ORG_ID,
            call_log_id=_CALL_LOG_ID,
            contact_phone=_PHONE,
            contact_email=_EMAIL,
            extraction_data=_EXTRACTION,
            ghl_contact_id="ghl-123",
        )
        assert result is not None
        assert db.add.called
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_creates_without_optional_fields(self):
        db = _mock_db()
        result = await create_engagement(
            db=db,
            org_id=_ORG_ID,
            call_log_id=_CALL_LOG_ID,
            contact_phone=_PHONE,
            contact_email=None,
            extraction_data=_EXTRACTION,
            ghl_contact_id=None,
        )
        assert result is not None
        assert db.add.called

    @pytest.mark.asyncio
    async def test_empty_extraction_data_uses_empty_dict(self):
        db = _mock_db()
        result = await create_engagement(
            db=db,
            org_id=_ORG_ID,
            call_log_id=_CALL_LOG_ID,
            contact_phone=_PHONE,
            contact_email=None,
            extraction_data={},
            ghl_contact_id=None,
        )
        assert result.extraction_data == {}


class TestUpdateTouchpoint:
    @pytest.mark.asyncio
    async def test_updates_valid_touchpoint(self):
        existing = SimpleNamespace(
            touchpoints={},
            updated_at=None,
        )
        db = _mock_db(scalar_result=existing)
        result = await update_touchpoint(
            db=db,
            call_log_id=_CALL_LOG_ID,
            touchpoint_key="t1_wa",
            message_data={
                "message_id": "wati-123",
                "template": "sneha_post_call_links",
                "status": "sent",
            },
        )
        assert result is not None
        assert "t1_wa" in existing.touchpoints
        assert existing.touchpoints["t1_wa"]["message_id"] == "wati-123"
        assert existing.touchpoints["t1_wa"]["sent_at"] is not None

    @pytest.mark.asyncio
    async def test_invalid_touchpoint_key_rejected(self):
        existing = SimpleNamespace(touchpoints={}, updated_at=None)
        db = _mock_db(scalar_result=existing)
        result = await update_touchpoint(
            db=db,
            call_log_id=_CALL_LOG_ID,
            touchpoint_key="invalid_key",
            message_data={"message_id": "123", "status": "sent"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_merges_with_existing_touchpoints(self):
        existing = SimpleNamespace(
            touchpoints={"t1_wa": {"message_id": "old", "status": "sent", "sent_at": "2026-04-01T10:00:00Z"}},
            updated_at=None,
        )
        db = _mock_db(scalar_result=existing)
        await update_touchpoint(
            db=db,
            call_log_id=_CALL_LOG_ID,
            touchpoint_key="t1_email",
            message_data={"message_id": "email-123", "conversation_id": "conv-456", "status": "sent"},
        )
        assert "t1_wa" in existing.touchpoints
        assert "t1_email" in existing.touchpoints

    @pytest.mark.asyncio
    async def test_returns_none_when_engagement_not_found(self):
        db = _mock_db(scalar_result=None)
        result = await update_touchpoint(
            db=db,
            call_log_id=_CALL_LOG_ID,
            touchpoint_key="t1_wa",
            message_data={"message_id": "123", "status": "sent"},
        )
        assert result is None


class TestUpdateReportLink:
    @pytest.mark.asyncio
    async def test_sets_report_link(self):
        existing = SimpleNamespace(report_link=None, updated_at=None)
        db = _mock_db(scalar_result=existing)
        result = await update_report_link(
            db=db,
            call_log_id=_CALL_LOG_ID,
            report_link="https://storage.googleapis.com/fwai-reports/roadmaps/test.pdf",
        )
        assert result is not None
        assert existing.report_link == "https://storage.googleapis.com/fwai-reports/roadmaps/test.pdf"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _mock_db(scalar_result=None)
        result = await update_report_link(db=db, call_log_id=_CALL_LOG_ID, report_link="https://x.pdf")
        assert result is None


class TestGetEngagement:
    @pytest.mark.asyncio
    async def test_returns_engagement_when_found(self):
        eng = SimpleNamespace(id=uuid.uuid4(), call_log_id=_CALL_LOG_ID)
        db = _mock_db(scalar_result=eng)
        result = await get_engagement(db=db, call_log_id=_CALL_LOG_ID)
        assert result is eng

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _mock_db(scalar_result=None)
        result = await get_engagement(db=db, call_log_id=_CALL_LOG_ID)
        assert result is None
