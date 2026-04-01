"""Tests for engagement API endpoint schemas and validation."""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace

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

from app.api.engagements import (
    CreateEngagementRequest,
    UpdateTouchpointRequest,
    UpdateReportLinkRequest,
)

_CALL_LOG_ID = uuid.uuid4()


class TestCreateEngagementRequest:
    def test_valid_request(self):
        req = CreateEngagementRequest(
            call_log_id=_CALL_LOG_ID,
            contact_phone="+919609775259",
            contact_email="test@example.com",
            extraction_data={
                "profession_spoken": "software engineer",
                "pain_or_goal": "wants to automate testing",
                "specific_task": "test cases",
            },
            ghl_contact_id="ghl-123",
        )
        assert req.call_log_id == _CALL_LOG_ID
        assert req.contact_phone == "+919609775259"
        assert req.extraction_data["profession_spoken"] == "software engineer"

    def test_optional_fields_default_none(self):
        req = CreateEngagementRequest(
            call_log_id=_CALL_LOG_ID,
            contact_phone="+919609775259",
            extraction_data={"profession_spoken": "teacher"},
        )
        assert req.contact_email is None
        assert req.ghl_contact_id is None

    def test_empty_extraction_data_allowed(self):
        req = CreateEngagementRequest(
            call_log_id=_CALL_LOG_ID,
            contact_phone="+919609775259",
            extraction_data={},
        )
        assert req.extraction_data == {}


class TestUpdateTouchpointRequest:
    def test_valid_wa_touchpoint(self):
        req = UpdateTouchpointRequest(
            touchpoint_key="t1_wa",
            message_id="wati-msg-123",
            template="sneha_post_call_links",
            status="sent",
        )
        assert req.touchpoint_key == "t1_wa"
        assert req.message_id == "wati-msg-123"

    def test_valid_email_touchpoint(self):
        req = UpdateTouchpointRequest(
            touchpoint_key="t1_email",
            message_id="ghl-msg-456",
            conversation_id="ghl-conv-789",
            subject="Great talking to you",
            status="sent",
        )
        assert req.conversation_id == "ghl-conv-789"
        assert req.subject == "Great talking to you"

    def test_optional_fields(self):
        req = UpdateTouchpointRequest(
            touchpoint_key="t2_wa",
            message_id="msg-1",
            status="sent",
        )
        assert req.conversation_id is None
        assert req.template is None
        assert req.subject is None


class TestUpdateReportLinkRequest:
    def test_valid_request(self):
        req = UpdateReportLinkRequest(
            report_link="https://storage.googleapis.com/fwai-reports/roadmaps/test.pdf",
        )
        assert "fwai-reports" in req.report_link

    def test_empty_link_rejected(self):
        with pytest.raises(Exception):
            UpdateReportLinkRequest(report_link="")
