# Lead Engagement Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store personalized engagement data and message analytics in Wavelength DB with API endpoints for n8n integration.

**Architecture:** New `lead_engagements` table with JSONB columns for extraction data and per-touchpoint message tracking. Service layer handles CRUD, API layer exposes endpoints for n8n to call after each send. Tests mock the DB session following existing patterns (test_dnc_service.py).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Alembic, pytest + pytest-asyncio

---

## File Structure

| File | Responsibility |
|---|---|
| `app/models/lead_engagement.py` | SQLAlchemy model for `lead_engagements` table |
| `app/services/engagement_service.py` | CRUD + analytics aggregation |
| `app/api/engagements.py` | REST endpoints for n8n integration |
| `alembic/versions/040_add_lead_engagements_table.py` | DB migration |
| `tests/test_engagement_service.py` | Unit tests for service layer |
| `tests/test_engagement_api.py` | Integration tests for API endpoints |
| `app/main.py` | Register router (1 line change) |

---

### Task 1: SQLAlchemy Model

**Files:**
- Create: `app/models/lead_engagement.py`

- [ ] **Step 1: Create the model file**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class LeadEngagement(Base):
    __tablename__ = "lead_engagements"
    __table_args__ = (
        Index("idx_lead_engagements_org", "org_id"),
        Index("idx_lead_engagements_phone", "contact_phone"),
        Index("idx_lead_engagements_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    call_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_logs.id"), unique=True, nullable=False
    )
    contact_phone: Mapped[str] = mapped_column(Text, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(Text)
    extraction_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    touchpoints: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    report_link: Mapped[str | None] = mapped_column(Text)
    ghl_contact_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile app/models/lead_engagement.py`
Expected: No output (clean compile)

- [ ] **Step 3: Commit**

```bash
git add app/models/lead_engagement.py
git commit -m "feat: add LeadEngagement SQLAlchemy model"
```

---

### Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/040_add_lead_engagements_table.py`

- [ ] **Step 1: Create migration**

```python
"""Add lead_engagements table.

Revision ID: 040
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("call_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), unique=True, nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("extraction_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("touchpoints", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("report_link", sa.Text(), nullable=True),
        sa.Column("ghl_contact_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_lead_engagements_org", "lead_engagements", ["org_id"])
    op.create_index("idx_lead_engagements_phone", "lead_engagements", ["contact_phone"])
    op.create_index("idx_lead_engagements_created", "lead_engagements", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_lead_engagements_created")
    op.drop_index("idx_lead_engagements_phone")
    op.drop_index("idx_lead_engagements_org")
    op.drop_table("lead_engagements")
```

- [ ] **Step 2: Commit**

```bash
git add alembic/versions/040_add_lead_engagements_table.py
git commit -m "feat: migration 040 — lead_engagements table"
```

---

### Task 3: Service Layer — Unit Tests First

**Files:**
- Create: `tests/test_engagement_service.py`
- Create: `app/services/engagement_service.py`

- [ ] **Step 1: Write unit tests**

```python
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
        assert "t1_wa" in existing.touchpoints  # old data preserved
        assert "t1_email" in existing.touchpoints  # new data added

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
```

- [ ] **Step 2: Run tests — should fail (service doesn't exist yet)**

Run: `python3 -m pytest tests/test_engagement_service.py -q --tb=line`
Expected: ImportError — `cannot import name 'create_engagement'`

- [ ] **Step 3: Implement the service**

```python
"""Lead engagement tracking service.

Stores Gemini extraction data and per-touchpoint message analytics
for the personalized engagement flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_engagement import LeadEngagement

logger = structlog.get_logger(__name__)

VALID_TOUCHPOINT_KEYS = frozenset({
    "t1_wa", "t1_email",
    "t2_wa", "t2_email",
    "t3_wa", "t3_email",
    "t4_wa", "t4_email",
    "t5_wa", "t5_email",
    "t6_wa", "t6_email",
    "t7_wa", "t7_email",
    "t8_wa", "t8_email",
})


async def create_engagement(
    db: AsyncSession,
    org_id: uuid.UUID,
    call_log_id: uuid.UUID,
    contact_phone: str,
    contact_email: str | None,
    extraction_data: dict,
    ghl_contact_id: str | None = None,
) -> LeadEngagement:
    """Create a new engagement record after Gemini extraction."""
    engagement = LeadEngagement(
        org_id=org_id,
        call_log_id=call_log_id,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extraction_data=extraction_data or {},
        ghl_contact_id=ghl_contact_id,
    )
    db.add(engagement)
    await db.commit()
    await db.refresh(engagement)
    logger.info(
        "engagement_created",
        engagement_id=str(engagement.id),
        call_log_id=str(call_log_id),
        phone=contact_phone,
    )
    return engagement


async def update_touchpoint(
    db: AsyncSession,
    call_log_id: uuid.UUID,
    touchpoint_key: str,
    message_data: dict,
) -> LeadEngagement | None:
    """Update a specific touchpoint's message data after send."""
    if touchpoint_key not in VALID_TOUCHPOINT_KEYS:
        logger.warning("invalid_touchpoint_key", key=touchpoint_key)
        return None

    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    engagement = result.scalar_one_or_none()
    if not engagement:
        logger.warning("engagement_not_found_for_touchpoint", call_log_id=str(call_log_id))
        return None

    tp = dict(engagement.touchpoints or {})
    tp[touchpoint_key] = {
        **message_data,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    engagement.touchpoints = tp
    engagement.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "touchpoint_updated",
        call_log_id=str(call_log_id),
        touchpoint=touchpoint_key,
        status=message_data.get("status"),
    )
    return engagement


async def update_report_link(
    db: AsyncSession,
    call_log_id: uuid.UUID,
    report_link: str,
) -> LeadEngagement | None:
    """Set the report PDF link after GCS upload."""
    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    engagement = result.scalar_one_or_none()
    if not engagement:
        logger.warning("engagement_not_found_for_report", call_log_id=str(call_log_id))
        return None

    engagement.report_link = report_link
    engagement.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("report_link_updated", call_log_id=str(call_log_id))
    return engagement


async def get_engagement(
    db: AsyncSession,
    call_log_id: uuid.UUID,
) -> LeadEngagement | None:
    """Retrieve engagement by call_log_id."""
    result = await db.execute(
        select(LeadEngagement).where(LeadEngagement.call_log_id == call_log_id)
    )
    return result.scalar_one_or_none()


async def get_engagement_by_phone(
    db: AsyncSession,
    org_id: uuid.UUID,
    contact_phone: str,
) -> LeadEngagement | None:
    """Retrieve most recent engagement by phone number."""
    result = await db.execute(
        select(LeadEngagement)
        .where(
            LeadEngagement.org_id == org_id,
            LeadEngagement.contact_phone == contact_phone,
        )
        .order_by(LeadEngagement.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 4: Run tests — all should pass**

Run: `python3 -m pytest tests/test_engagement_service.py -q --tb=short`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/engagement_service.py tests/test_engagement_service.py
git commit -m "feat: engagement service with unit tests"
```

---

### Task 4: API Endpoints — Tests First

**Files:**
- Create: `tests/test_engagement_api.py`
- Create: `app/api/engagements.py`

- [ ] **Step 1: Write API tests**

```python
"""Tests for engagement API endpoints.

These test the Pydantic schemas and request/response shapes.
Full integration tests require a real DB (covered in deployment testing).
"""

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
```

- [ ] **Step 2: Implement the API**

```python
"""Lead engagement tracking API.

Endpoints for n8n to create engagement records and update
touchpoint message data after each WATI/GHL send.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.engagement_service import (
    create_engagement,
    get_engagement,
    get_engagement_by_phone,
    update_report_link,
    update_touchpoint,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/engagements", tags=["engagements"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateEngagementRequest(BaseModel):
    call_log_id: uuid.UUID
    contact_phone: str
    contact_email: str | None = None
    extraction_data: dict = Field(default_factory=dict)
    ghl_contact_id: str | None = None


class CreateEngagementResponse(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID
    status: str = "created"


class UpdateTouchpointRequest(BaseModel):
    touchpoint_key: str
    message_id: str
    conversation_id: str | None = None
    template: str | None = None
    subject: str | None = None
    status: str = "sent"


class UpdateTouchpointResponse(BaseModel):
    call_log_id: uuid.UUID
    touchpoint_key: str
    status: str = "updated"


class UpdateReportLinkRequest(BaseModel):
    report_link: str

    @field_validator("report_link")
    @classmethod
    def report_link_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("report_link cannot be empty")
        return v


class EngagementResponse(BaseModel):
    id: uuid.UUID
    call_log_id: uuid.UUID
    contact_phone: str
    contact_email: str | None
    extraction_data: dict
    touchpoints: dict
    report_link: str | None
    ghl_contact_id: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def api_create_engagement(
    body: CreateEngagementRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateEngagementResponse:
    """Create engagement record after Gemini extraction. Called by n8n."""
    # Look up call_log to get org_id
    from app.models.call_log import CallLog
    from sqlalchemy import select

    result = await db.execute(select(CallLog).where(CallLog.id == body.call_log_id))
    call_log = result.scalar_one_or_none()
    if not call_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call log {body.call_log_id} not found",
        )

    try:
        engagement = await create_engagement(
            db=db,
            org_id=call_log.org_id,
            call_log_id=body.call_log_id,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
            extraction_data=body.extraction_data,
            ghl_contact_id=body.ghl_contact_id,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Engagement already exists for call_log_id {body.call_log_id}",
            )
        raise

    return CreateEngagementResponse(id=engagement.id, call_log_id=engagement.call_log_id)


@router.patch("/{call_log_id}/touchpoint")
async def api_update_touchpoint(
    call_log_id: uuid.UUID,
    body: UpdateTouchpointRequest,
    db: AsyncSession = Depends(get_db),
) -> UpdateTouchpointResponse:
    """Update touchpoint message data after a send. Called by n8n."""
    message_data = {
        "message_id": body.message_id,
        "status": body.status,
    }
    if body.conversation_id:
        message_data["conversation_id"] = body.conversation_id
    if body.template:
        message_data["template"] = body.template
    if body.subject:
        message_data["subject"] = body.subject

    result = await update_touchpoint(
        db=db,
        call_log_id=call_log_id,
        touchpoint_key=body.touchpoint_key,
        message_data=message_data,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id} or invalid touchpoint key",
        )

    return UpdateTouchpointResponse(call_log_id=call_log_id, touchpoint_key=body.touchpoint_key)


@router.patch("/{call_log_id}/report-link")
async def api_update_report_link(
    call_log_id: uuid.UUID,
    body: UpdateReportLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set report PDF link after GCS upload. Called by n8n."""
    result = await update_report_link(db=db, call_log_id=call_log_id, report_link=body.report_link)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id}",
        )
    return {"call_log_id": str(call_log_id), "status": "updated"}


@router.get("/{call_log_id}")
async def api_get_engagement(
    call_log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EngagementResponse:
    """Get full engagement record."""
    engagement = await get_engagement(db=db, call_log_id=call_log_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engagement not found for call_log_id {call_log_id}",
        )
    return EngagementResponse(
        id=engagement.id,
        call_log_id=engagement.call_log_id,
        contact_phone=engagement.contact_phone,
        contact_email=engagement.contact_email,
        extraction_data=engagement.extraction_data,
        touchpoints=engagement.touchpoints,
        report_link=engagement.report_link,
        ghl_contact_id=engagement.ghl_contact_id,
        created_at=engagement.created_at.isoformat() if engagement.created_at else "",
        updated_at=engagement.updated_at.isoformat() if engagement.updated_at else "",
    )
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_engagement_api.py tests/test_engagement_service.py -q --tb=short`
Expected: All pass (17+ tests)

- [ ] **Step 4: Commit**

```bash
git add app/api/engagements.py tests/test_engagement_api.py
git commit -m "feat: engagement API endpoints with tests"
```

---

### Task 5: Register Router in main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add import and include_router**

Find the block where other routers are included (look for `app.include_router`). Add:

```python
from app.api import engagements
```

And in the router registration section:

```python
app.include_router(engagements.router)
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile app/main.py`
Expected: No output (clean compile)

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: register engagements router"
```

---

### Task 6: Run Full Test Suite

- [ ] **Step 1: Run all engagement tests**

Run: `python3 -m pytest tests/test_engagement_service.py tests/test_engagement_api.py -v --tb=short`
Expected: All pass

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `python3 -m pytest tests/test_n8n_payload.py tests/test_n8n_conditions.py tests/test_contact_email_flow.py tests/test_call_analyzer_unit.py tests/test_dnc_service.py tests/test_callback_scheduler.py tests/test_call_memory.py tests/test_comfort_noise_ambient.py tests/test_engagement_service.py tests/test_engagement_api.py -q --tb=short`
Expected: 280+ passed, 0 failed

- [ ] **Step 3: Final commit with all files**

```bash
git add -A
git commit -m "feat: lead engagement tracking system — model, service, API, tests"
```

---

### Task 7: Deploy

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Deploy backend with migration**

```bash
gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e -- \
  'cd /home/animeshmahato/wavelength-v3 && sudo git pull origin main && sudo docker compose build backend && sudo docker compose up -d backend && sleep 5 && sudo docker compose exec backend alembic upgrade head'
```

Expected: `Running upgrade 039 -> 040, Add lead_engagements table.`

- [ ] **Step 3: Verify deployment**

Test the API endpoint:
```bash
curl -s https://voice.freedomwithai.com/api/engagements/00000000-0000-0000-0000-000000000000 | python3 -m json.tool
```
Expected: 404 with "Engagement not found" (proves the endpoint is live)
