"""Tests for billing API Pydantic schemas and provider restriction constants."""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.api.billing import (
    AddCreditsRequest,
    AdjustCreditsRequest,
    BalanceResponse,
    TransactionListResponse,
    TransactionResponse,
    CreditBalanceResponse,
    OrgBalanceResponse,
)

from app.api.bots import ADMIN_ONLY_TTS, ADMIN_ONLY_STT


# ---------------------------------------------------------------------------
# AddCreditsRequest
# ---------------------------------------------------------------------------

class TestAddCreditsRequest:
    def test_valid_request(self):
        req = AddCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            description="Test topup",
        )
        assert req.amount == Decimal("100.00")

    def test_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            AddCreditsRequest(
                org_id=uuid.uuid4(),
                amount=Decimal("0"),
            )

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            AddCreditsRequest(
                org_id=uuid.uuid4(),
                amount=Decimal("-10"),
            )

    def test_description_optional(self):
        req = AddCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("50"),
        )
        assert req.description is None

    def test_small_amount_accepted(self):
        req = AddCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("0.01"),
        )
        assert req.amount == Decimal("0.01")


# ---------------------------------------------------------------------------
# AdjustCreditsRequest
# ---------------------------------------------------------------------------

class TestAdjustCreditsRequest:
    def test_positive_adjustment(self):
        req = AdjustCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("25"),
        )
        assert req.amount == Decimal("25")

    def test_negative_adjustment(self):
        req = AdjustCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("-25"),
        )
        assert req.amount == Decimal("-25")

    def test_zero_is_valid_schema_wise(self):
        """Zero is valid at schema level; the endpoint rejects it."""
        req = AdjustCreditsRequest(
            org_id=uuid.uuid4(),
            amount=Decimal("0"),
        )
        assert req.amount == Decimal("0")


# ---------------------------------------------------------------------------
# BalanceResponse
# ---------------------------------------------------------------------------

class TestBalanceResponse:
    def test_valid(self):
        resp = BalanceResponse(balance=100.5, org_id=uuid.uuid4())
        assert resp.balance == 100.5

    def test_zero_balance(self):
        resp = BalanceResponse(balance=0.0, org_id=uuid.uuid4())
        assert resp.balance == 0.0

    def test_negative_balance(self):
        resp = BalanceResponse(balance=-5.0, org_id=uuid.uuid4())
        assert resp.balance == -5.0


# ---------------------------------------------------------------------------
# TransactionListResponse
# ---------------------------------------------------------------------------

class TestTransactionListResponse:
    def test_empty_list(self):
        resp = TransactionListResponse(items=[], total=0, page=1, page_size=20)
        assert resp.items == []
        assert resp.total == 0

    def test_pagination_fields(self):
        resp = TransactionListResponse(items=[], total=50, page=3, page_size=10)
        assert resp.page == 3
        assert resp.page_size == 10


# ---------------------------------------------------------------------------
# OrgBalanceResponse
# ---------------------------------------------------------------------------

class TestOrgBalanceResponse:
    def test_valid(self):
        resp = OrgBalanceResponse(
            org_id=uuid.uuid4(),
            org_name="Test Org",
            credit_balance=500.0,
        )
        assert resp.org_name == "Test Org"
        assert resp.credit_balance == 500.0


# ---------------------------------------------------------------------------
# model_dump tests
# ---------------------------------------------------------------------------

class TestModelDump:
    def test_balance_response_model_dump(self):
        oid = uuid.uuid4()
        resp = BalanceResponse(balance=42.5, org_id=oid)
        data = resp.model_dump()
        assert data["balance"] == 42.5
        assert data["org_id"] == oid
        assert isinstance(data, dict)

    def test_org_balance_response_model_dump(self):
        oid = uuid.uuid4()
        resp = OrgBalanceResponse(org_id=oid, org_name="Acme", credit_balance=123.0)
        data = resp.model_dump()
        assert data["org_id"] == oid
        assert data["org_name"] == "Acme"
        assert data["credit_balance"] == 123.0
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Provider restriction constants
# ---------------------------------------------------------------------------

class TestProviderRestrictions:
    def test_admin_only_tts_providers(self):
        assert "gemini" in ADMIN_ONLY_TTS
        assert "elevenlabs" in ADMIN_ONLY_TTS
        assert "sarvam" not in ADMIN_ONLY_TTS

    def test_admin_only_stt_providers(self):
        assert "smallest" in ADMIN_ONLY_STT
        assert "deepgram" not in ADMIN_ONLY_STT

    def test_provider_sets_are_sets(self):
        assert isinstance(ADMIN_ONLY_TTS, set)
        assert isinstance(ADMIN_ONLY_STT, set)
