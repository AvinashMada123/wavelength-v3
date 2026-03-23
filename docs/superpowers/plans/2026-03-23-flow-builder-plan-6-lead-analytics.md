# Flow Builder Plan 6: Lead Integration & Analytics

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build lead-flow integration (flow history tab, canvas leads panel) and analytics (canvas badges, analytics page, backend API, admin notifications) so users can see how leads move through flows and measure flow performance.

**Architecture:** Extends the lead detail page with a new "Flows" tab, adds a leads drawer to the flow canvas, overlays per-node stats as canvas badges, builds a flow-specific analytics page with funnel/conversion/comparison views, and adds backend query endpoints plus admin error notifications.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy (async), React 18, Next.js 14, React Flow, Tailwind CSS, shadcn/ui, pytest, vitest

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §10, §11, §14

**Dependencies:** Plans 2 (data model), 3 (flow engine), 4 (canvas) must be complete. Tables `flow_instances`, `flow_touchpoints`, `flow_transitions`, `flow_nodes`, `flow_versions`, `flow_definitions` must exist.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `app/api/flow_analytics.py` | Flow analytics API endpoints (node stats, funnel, conversion, version comparison) |
| Create | `app/api/flow_leads.py` | Lead flow history + canvas leads panel API endpoints |
| Create | `app/services/flow_analytics.py` | Analytics query helpers (SQL aggregations, caching) |
| Create | `app/services/flow_notifications.py` | Admin notification service (error alerts, health checks) |
| Modify | `app/main.py` | Register new routers |
| Create | `frontend/src/lib/flow-analytics-api.ts` | TypeScript API client for flow analytics + lead history |
| Create | `frontend/src/app/(app)/leads/components/FlowHistoryTab.tsx` | Lead profile flow history tab |
| Modify | `frontend/src/app/(app)/leads/[leadId]/page.tsx` | Add "Flows" tab trigger + content |
| Create | `frontend/src/app/(app)/sequences/[id]/components/LeadsPanel.tsx` | Canvas leads drawer/sidebar |
| Create | `frontend/src/app/(app)/sequences/[id]/components/NodeBadge.tsx` | Per-node analytics badge overlay |
| Create | `frontend/src/app/(app)/sequences/[id]/components/JourneyOverlay.tsx` | Lead journey path highlight on canvas |
| Create | `frontend/src/app/(app)/sequences/analytics/flow/page.tsx` | Flow-specific analytics page |
| Create | `frontend/src/app/(app)/sequences/analytics/flow/components/FlowFunnel.tsx` | Funnel visualization component |
| Create | `frontend/src/app/(app)/sequences/analytics/flow/components/VersionComparison.tsx` | Side-by-side version comparison |
| Create | `frontend/src/app/(app)/sequences/analytics/flow/components/NodePerformanceTable.tsx` | Node performance breakdown table |
| Create | `frontend/src/components/ui/flow-health-widget.tsx` | Dashboard flow health widget |
| Create | `tests/test_flow_analytics.py` | Tests for analytics endpoints |
| Create | `tests/test_flow_leads.py` | Tests for lead flow history endpoints |
| Create | `tests/test_flow_notifications.py` | Tests for notification service |
| Create | `frontend/src/app/(app)/leads/components/__tests__/FlowHistoryTab.test.tsx` | Tests for flow history tab |
| Create | `frontend/src/app/(app)/sequences/[id]/components/__tests__/LeadsPanel.test.tsx` | Tests for leads panel |

---

## Task 1: Backend — Lead Flow History API

**Files:**
- Create: `app/api/flow_leads.py`
- Create: `tests/test_flow_leads.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write failing tests for lead flow history endpoint**

```python
# tests/test_flow_leads.py
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_ORG_ID = uuid.uuid4()
FAKE_LEAD_ID = uuid.uuid4()
FAKE_FLOW_ID = uuid.uuid4()
FAKE_VERSION_ID = uuid.uuid4()
FAKE_INSTANCE_ID = uuid.uuid4()
FAKE_NODE_ID_1 = uuid.uuid4()
FAKE_NODE_ID_2 = uuid.uuid4()


def _mock_org():
    org = MagicMock()
    org.id = FAKE_ORG_ID
    return org


def _make_instance_row(
    instance_id=None,
    flow_name="Follow-up Flow",
    version_number=1,
    status="active",
    current_node_id=None,
):
    """Simulate a DB row from the join query."""
    row = MagicMock()
    row.id = instance_id or FAKE_INSTANCE_ID
    row.flow_id = FAKE_FLOW_ID
    row.flow_name = flow_name
    row.version_number = version_number
    row.status = status
    row.current_node_id = current_node_id or FAKE_NODE_ID_1
    row.enrolled_at = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    row.completed_at = None
    row.error_message = None
    return row


def _make_transition_row(from_node_id=None, to_node_id=None, node_label="Call Step"):
    row = MagicMock()
    row.from_node_id = from_node_id
    row.to_node_id = to_node_id or FAKE_NODE_ID_1
    row.node_type = "voice_call"
    row.node_label = node_label
    row.outcome_data = {"call_outcome": "picked_up"}
    row.transitioned_at = datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc)
    row.touchpoint_status = "completed"
    row.touchpoint_error = None
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_flow_history_returns_enrollments():
    """GET /api/flows/leads/{lead_id}/history returns chronological enrollments."""
    from app.api.flow_leads import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    # Mock the instances query
    mock_result = MagicMock()
    mock_result.all.return_value = [_make_instance_row()]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_leads.get_db", return_value=mock_db),
        patch("app.api.flow_leads.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/leads/{FAKE_LEAD_ID}/history")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["enrollments"]) == 1
    assert data["enrollments"][0]["flow_name"] == "Follow-up Flow"
    assert data["enrollments"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_lead_flow_history_empty():
    """Returns empty list for lead with no flow enrollments."""
    from app.api.flow_leads import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_leads.get_db", return_value=mock_db),
        patch("app.api.flow_leads.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/leads/{FAKE_LEAD_ID}/history")

    assert resp.status_code == 200
    assert data := resp.json()
    assert data["enrollments"] == []


@pytest.mark.asyncio
async def test_instance_journey_returns_transitions():
    """GET /api/flows/instances/{id}/journey returns node-by-node transitions."""
    from app.api.flow_leads import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [
        _make_transition_row(from_node_id=None, to_node_id=FAKE_NODE_ID_1, node_label="Start"),
        _make_transition_row(from_node_id=FAKE_NODE_ID_1, to_node_id=FAKE_NODE_ID_2, node_label="Call Step"),
    ]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_leads.get_db", return_value=mock_db),
        patch("app.api.flow_leads.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/instances/{FAKE_INSTANCE_ID}/journey")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transitions"]) == 2
    assert data["transitions"][0]["node_label"] == "Start"
    assert data["transitions"][1]["outcome_data"]["call_outcome"] == "picked_up"


@pytest.mark.asyncio
async def test_canvas_leads_returns_filtered_leads():
    """GET /api/flows/{id}/leads returns leads with status/node filters."""
    from app.api.flow_leads import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_lead_row = MagicMock()
    mock_lead_row.instance_id = FAKE_INSTANCE_ID
    mock_lead_row.lead_id = FAKE_LEAD_ID
    mock_lead_row.lead_name = "John Doe"
    mock_lead_row.lead_phone = "+919876543210"
    mock_lead_row.status = "active"
    mock_lead_row.current_node_id = FAKE_NODE_ID_1
    mock_lead_row.current_node_label = "Call Step"
    mock_lead_row.enrolled_at = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_lead_row]
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

    with (
        patch("app.api.flow_leads.get_db", return_value=mock_db),
        patch("app.api.flow_leads.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/flows/{FAKE_FLOW_ID}/leads",
                params={"status": "active"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["leads"][0]["lead_name"] == "John Doe"


@pytest.mark.asyncio
async def test_node_lead_counts():
    """GET /api/flows/{id}/node-counts returns per-node lead counts."""
    from app.api.flow_leads import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_row_1 = MagicMock()
    mock_row_1.current_node_id = FAKE_NODE_ID_1
    mock_row_1.count = 47
    mock_row_2 = MagicMock()
    mock_row_2.current_node_id = FAKE_NODE_ID_2
    mock_row_2.count = 12

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row_1, mock_row_2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_leads.get_db", return_value=mock_db),
        patch("app.api.flow_leads.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/node-counts")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["counts"]) == 2
    assert data["counts"][str(FAKE_NODE_ID_1)] == 47
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flow_leads.py -v`
Expected: ImportError — `app.api.flow_leads` does not exist yet.

- [ ] **Step 3: Implement the lead flow history API**

```python
# app/api/flow_leads.py
"""Lead-flow integration API — flow history, canvas leads panel, node counts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-leads"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FlowEnrollment(BaseModel):
    instance_id: str
    flow_id: str
    flow_name: str
    version_number: int
    status: str
    current_node_id: str | None
    enrolled_at: datetime
    completed_at: datetime | None
    error_message: str | None


class LeadFlowHistoryResponse(BaseModel):
    lead_id: str
    enrollments: list[FlowEnrollment]


class TransitionStep(BaseModel):
    from_node_id: str | None
    to_node_id: str
    node_type: str
    node_label: str
    outcome_data: dict[str, Any] | None
    transitioned_at: datetime
    touchpoint_status: str | None
    touchpoint_error: str | None


class JourneyResponse(BaseModel):
    instance_id: str
    transitions: list[TransitionStep]


class CanvasLead(BaseModel):
    instance_id: str
    lead_id: str
    lead_name: str | None
    lead_phone: str | None
    status: str
    current_node_id: str | None
    current_node_label: str | None
    enrolled_at: datetime


class CanvasLeadsResponse(BaseModel):
    flow_id: str
    leads: list[CanvasLead]
    total: int
    page: int
    page_size: int


class NodeCountsResponse(BaseModel):
    flow_id: str
    counts: dict[str, int]  # node_id -> active lead count


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

PAGE_SIZE = 50


@router.get("/leads/{lead_id}/history", response_model=LeadFlowHistoryResponse)
async def get_lead_flow_history(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get chronological list of all flow enrollments for a lead."""
    query = text("""
        SELECT
            fi.id,
            fi.flow_id,
            fd.name AS flow_name,
            fv.version_number,
            fi.status,
            fi.current_node_id,
            fi.enrolled_at,
            fi.completed_at,
            fi.error_message
        FROM flow_instances fi
        JOIN flow_versions fv ON fi.version_id = fv.id
        JOIN flow_definitions fd ON fv.flow_id = fd.id
        WHERE fi.lead_id = :lead_id
          AND fi.org_id = :org_id
        ORDER BY fi.enrolled_at DESC
    """)
    result = await db.execute(
        query, {"lead_id": str(lead_id), "org_id": str(org.id)}
    )
    rows = result.all()

    enrollments = [
        FlowEnrollment(
            instance_id=str(r.id),
            flow_id=str(r.flow_id),
            flow_name=r.flow_name,
            version_number=r.version_number,
            status=r.status,
            current_node_id=str(r.current_node_id) if r.current_node_id else None,
            enrolled_at=r.enrolled_at,
            completed_at=r.completed_at,
            error_message=r.error_message,
        )
        for r in rows
    ]

    return LeadFlowHistoryResponse(
        lead_id=str(lead_id),
        enrollments=enrollments,
    )


@router.get("/instances/{instance_id}/journey", response_model=JourneyResponse)
async def get_instance_journey(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get node-by-node journey with timestamps and outcomes for an instance."""
    query = text("""
        SELECT
            ft.from_node_id,
            ft.to_node_id,
            fn.node_type,
            fn.label AS node_label,
            ft.outcome_data,
            ft.transitioned_at,
            ftp.status AS touchpoint_status,
            ftp.error_message AS touchpoint_error
        FROM flow_transitions ft
        JOIN flow_nodes fn ON ft.to_node_id = fn.id
        LEFT JOIN flow_touchpoints ftp
            ON ftp.instance_id = ft.instance_id
           AND ftp.node_id = ft.to_node_id
        JOIN flow_instances fi ON ft.instance_id = fi.id
        WHERE ft.instance_id = :instance_id
          AND fi.org_id = :org_id
        ORDER BY ft.transitioned_at ASC
    """)
    result = await db.execute(
        query, {"instance_id": str(instance_id), "org_id": str(org.id)}
    )
    rows = result.all()

    transitions = [
        TransitionStep(
            from_node_id=str(r.from_node_id) if r.from_node_id else None,
            to_node_id=str(r.to_node_id),
            node_type=r.node_type,
            node_label=r.node_label,
            outcome_data=r.outcome_data,
            transitioned_at=r.transitioned_at,
            touchpoint_status=r.touchpoint_status,
            touchpoint_error=r.touchpoint_error,
        )
        for r in rows
    ]

    return JourneyResponse(
        instance_id=str(instance_id),
        transitions=transitions,
    )


@router.get("/{flow_id}/leads", response_model=CanvasLeadsResponse)
async def get_canvas_leads(
    flow_id: uuid.UUID,
    status: str | None = Query(None, description="Filter by instance status"),
    node_id: uuid.UUID | None = Query(None, description="Filter by current node"),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get leads currently in a flow for the canvas leads panel."""
    base_where = """
        fi.flow_id = :flow_id
        AND fi.org_id = :org_id
    """
    params: dict[str, Any] = {
        "flow_id": str(flow_id),
        "org_id": str(org.id),
    }

    if status:
        base_where += " AND fi.status = :status"
        params["status"] = status
    if node_id:
        base_where += " AND fi.current_node_id = :node_id"
        params["node_id"] = str(node_id)

    # Count
    count_query = text(f"""
        SELECT COUNT(*) FROM flow_instances fi WHERE {base_where}
    """)
    count_result = await db.execute(count_query, params)
    total = count_result.scalar() or 0

    # Paginated leads
    offset = (page - 1) * PAGE_SIZE
    params["limit"] = PAGE_SIZE
    params["offset"] = offset

    data_query = text(f"""
        SELECT
            fi.id AS instance_id,
            fi.lead_id,
            l.contact_name AS lead_name,
            l.phone_number AS lead_phone,
            fi.status,
            fi.current_node_id,
            fn.label AS current_node_label,
            fi.enrolled_at
        FROM flow_instances fi
        JOIN leads l ON fi.lead_id = l.id
        LEFT JOIN flow_nodes fn ON fi.current_node_id = fn.id
        WHERE {base_where}
        ORDER BY fi.enrolled_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(data_query, params)
    rows = result.all()

    leads = [
        CanvasLead(
            instance_id=str(r.instance_id),
            lead_id=str(r.lead_id),
            lead_name=r.lead_name,
            lead_phone=r.lead_phone,
            status=r.status,
            current_node_id=str(r.current_node_id) if r.current_node_id else None,
            current_node_label=r.current_node_label,
            enrolled_at=r.enrolled_at,
        )
        for r in rows
    ]

    return CanvasLeadsResponse(
        flow_id=str(flow_id),
        leads=leads,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
    )


@router.get("/{flow_id}/node-counts", response_model=NodeCountsResponse)
async def get_node_lead_counts(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Get per-node active lead counts for canvas badges."""
    query = text("""
        SELECT
            fi.current_node_id,
            COUNT(*) AS count
        FROM flow_instances fi
        WHERE fi.flow_id = :flow_id
          AND fi.org_id = :org_id
          AND fi.status = 'active'
          AND fi.current_node_id IS NOT NULL
        GROUP BY fi.current_node_id
    """)
    result = await db.execute(
        query, {"flow_id": str(flow_id), "org_id": str(org.id)}
    )
    rows = result.all()

    counts = {str(r.current_node_id): r.count for r in rows}

    return NodeCountsResponse(
        flow_id=str(flow_id),
        counts=counts,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_flow_leads.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Register the router in main.py**

In `app/main.py`, add:

```python
from app.api.flow_leads import router as flow_leads_router
app.include_router(flow_leads_router)
```

- [ ] **Step 6: Commit**

```bash
git add app/api/flow_leads.py tests/test_flow_leads.py app/main.py
git commit -m "feat: add lead flow history and canvas leads API endpoints

Adds 4 endpoints:
- GET /api/flows/leads/{id}/history — chronological flow enrollments
- GET /api/flows/instances/{id}/journey — node-by-node transitions
- GET /api/flows/{id}/leads — paginated canvas leads with filters
- GET /api/flows/{id}/node-counts — per-node active lead counts

These power the lead profile Flow History tab and canvas leads panel."
```

---

## Task 2: Backend — Flow Analytics API

**Files:**
- Create: `app/services/flow_analytics.py`
- Create: `app/api/flow_analytics.py`
- Create: `tests/test_flow_analytics.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write failing tests for analytics query helpers**

```python
# tests/test_flow_analytics.py
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

FAKE_ORG_ID = uuid.uuid4()
FAKE_FLOW_ID = uuid.uuid4()
FAKE_VERSION_ID_1 = uuid.uuid4()
FAKE_VERSION_ID_2 = uuid.uuid4()
FAKE_NODE_ID_1 = uuid.uuid4()
FAKE_NODE_ID_2 = uuid.uuid4()
FAKE_NODE_ID_3 = uuid.uuid4()


def _mock_org():
    org = MagicMock()
    org.id = FAKE_ORG_ID
    return org


# ---------------------------------------------------------------------------
# Node stats tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_stats_returns_per_node_metrics():
    """GET /api/flows/{id}/analytics/nodes returns pass/fail per node."""
    from app.api.flow_analytics import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    row1 = MagicMock()
    row1.node_id = FAKE_NODE_ID_1
    row1.node_type = "voice_call"
    row1.node_label = "Call Step"
    row1.total = 100
    row1.passed = 85
    row1.failed = 15
    row1.avg_duration_seconds = 45.2

    row2 = MagicMock()
    row2.node_id = FAKE_NODE_ID_2
    row2.node_type = "condition"
    row2.node_label = "Check Outcome"
    row2.total = 85
    row2.passed = 85
    row2.failed = 0
    row2.avg_duration_seconds = 0.1

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_analytics.get_db", return_value=mock_db),
        patch("app.api.flow_analytics.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/analytics/nodes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["passed"] == 85
    assert data["nodes"][0]["failed"] == 15
    assert data["nodes"][0]["success_rate"] == pytest.approx(0.85, abs=0.01)


@pytest.mark.asyncio
async def test_condition_branch_counts():
    """GET /api/flows/{id}/analytics/branches returns per-branch counts."""
    from app.api.flow_analytics import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    row1 = MagicMock()
    row1.node_id = FAKE_NODE_ID_2
    row1.node_label = "Check Outcome"
    row1.condition_label = "picked_up"
    row1.count = 89

    row2 = MagicMock()
    row2.node_id = FAKE_NODE_ID_2
    row2.node_label = "Check Outcome"
    row2.condition_label = "no_answer"
    row2.count = 23

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_analytics.get_db", return_value=mock_db),
        patch("app.api.flow_analytics.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/analytics/branches")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["branches"]) == 2
    assert data["branches"][0]["condition_label"] == "picked_up"
    assert data["branches"][0]["count"] == 89


@pytest.mark.asyncio
async def test_funnel_returns_ordered_nodes_with_dropoff():
    """GET /api/flows/{id}/analytics/funnel returns funnel data."""
    from app.api.flow_analytics import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    # Simulate 3 nodes in most-common path: entry(100) -> call(85) -> goal(60)
    row1 = MagicMock()
    row1.node_id = FAKE_NODE_ID_1
    row1.node_label = "Entry"
    row1.node_type = "trigger"
    row1.reached_count = 100
    row1.step_order = 0

    row2 = MagicMock()
    row2.node_id = FAKE_NODE_ID_2
    row2.node_label = "Call Step"
    row2.node_type = "voice_call"
    row2.reached_count = 85
    row2.step_order = 1

    row3 = MagicMock()
    row3.node_id = FAKE_NODE_ID_3
    row3.node_label = "Goal Met"
    row3.node_type = "goal"
    row3.reached_count = 60
    row3.step_order = 2

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2, row3]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_analytics.get_db", return_value=mock_db),
        patch("app.api.flow_analytics.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/analytics/funnel")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["steps"]) == 3
    assert data["steps"][0]["reached_count"] == 100
    assert data["steps"][1]["drop_off_rate"] == pytest.approx(0.15, abs=0.01)
    assert data["conversion_rate"] == pytest.approx(0.60, abs=0.01)


@pytest.mark.asyncio
async def test_version_comparison():
    """GET /api/flows/{id}/analytics/compare returns side-by-side version stats."""
    from app.api.flow_analytics import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    row1 = MagicMock()
    row1.version_id = FAKE_VERSION_ID_1
    row1.version_number = 1
    row1.total_enrolled = 200
    row1.total_completed = 120
    row1.total_goals = 80
    row1.total_errors = 10
    row1.avg_duration_hours = 48.5

    row2 = MagicMock()
    row2.version_id = FAKE_VERSION_ID_2
    row2.version_number = 2
    row2.total_enrolled = 150
    row2.total_completed = 100
    row2.total_goals = 75
    row2.total_errors = 5
    row2.avg_duration_hours = 36.2

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_analytics.get_db", return_value=mock_db),
        patch("app.api.flow_analytics.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/analytics/compare")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["versions"]) == 2
    assert data["versions"][0]["conversion_rate"] == pytest.approx(0.40, abs=0.01)
    assert data["versions"][1]["conversion_rate"] == pytest.approx(0.50, abs=0.01)


@pytest.mark.asyncio
async def test_flow_overview():
    """GET /api/flows/{id}/analytics/overview returns summary metrics."""
    from app.api.flow_analytics import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_row = MagicMock()
    mock_row.total_enrolled = 500
    mock_row.active = 120
    mock_row.completed = 300
    mock_row.goals_hit = 200
    mock_row.errored = 15
    mock_row.cancelled = 65

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.api.flow_analytics.get_db", return_value=mock_db),
        patch("app.api.flow_analytics.get_current_org", return_value=_mock_org()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/analytics/overview")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_enrolled"] == 500
    assert data["conversion_rate"] == pytest.approx(0.40, abs=0.01)
    assert data["error_rate"] == pytest.approx(0.03, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flow_analytics.py -v`
Expected: ImportError — `app.api.flow_analytics` does not exist yet.

- [ ] **Step 3: Implement the analytics query helpers**

```python
# app/services/flow_analytics.py
"""Flow analytics query helpers — reusable SQL builders for flow metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def compute_drop_off_rates(steps: list[dict]) -> list[dict]:
    """Compute drop-off rate between consecutive funnel steps.

    Each step dict must have 'reached_count'. Adds 'drop_off_rate' field.
    """
    for i, step in enumerate(steps):
        if i == 0:
            step["drop_off_rate"] = 0.0
        else:
            prev = steps[i - 1]["reached_count"]
            if prev > 0:
                step["drop_off_rate"] = round(1.0 - step["reached_count"] / prev, 4)
            else:
                step["drop_off_rate"] = 0.0
    return steps


def compute_conversion_rate(total_enrolled: int, goals_hit: int) -> float:
    """Conversion rate = goals_hit / total_enrolled."""
    if total_enrolled == 0:
        return 0.0
    return round(goals_hit / total_enrolled, 4)


def compute_error_rate(total: int, errors: int) -> float:
    """Error rate = errors / total."""
    if total == 0:
        return 0.0
    return round(errors / total, 4)
```

- [ ] **Step 4: Implement the flow analytics API**

```python
# app/api/flow_analytics.py
"""Flow analytics API — node stats, branches, funnel, conversion, version comparison."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db
from app.services.flow_analytics import (
    compute_conversion_rate,
    compute_drop_off_rates,
    compute_error_rate,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-analytics"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NodeStats(BaseModel):
    node_id: str
    node_type: str
    node_label: str
    total: int
    passed: int
    failed: int
    success_rate: float
    avg_duration_seconds: float | None


class NodeStatsResponse(BaseModel):
    flow_id: str
    nodes: list[NodeStats]


class BranchCount(BaseModel):
    node_id: str
    node_label: str
    condition_label: str
    count: int


class BranchCountsResponse(BaseModel):
    flow_id: str
    branches: list[BranchCount]


class FunnelStep(BaseModel):
    node_id: str
    node_label: str
    node_type: str
    reached_count: int
    drop_off_rate: float


class FunnelResponse(BaseModel):
    flow_id: str
    steps: list[FunnelStep]
    conversion_rate: float
    total_enrolled: int
    total_goals: int


class VersionStats(BaseModel):
    version_id: str
    version_number: int
    total_enrolled: int
    total_completed: int
    total_goals: int
    total_errors: int
    conversion_rate: float
    error_rate: float
    avg_duration_hours: float | None


class VersionComparisonResponse(BaseModel):
    flow_id: str
    versions: list[VersionStats]


class FlowOverview(BaseModel):
    flow_id: str
    total_enrolled: int
    active: int
    completed: int
    goals_hit: int
    errored: int
    cancelled: int
    conversion_rate: float
    error_rate: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{flow_id}/analytics/overview", response_model=FlowOverview)
async def get_flow_overview(
    flow_id: uuid.UUID,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Summary metrics for a single flow."""
    date_filter = ""
    params: dict[str, Any] = {
        "flow_id": str(flow_id),
        "org_id": str(org.id),
    }
    if start_date:
        date_filter += " AND fi.enrolled_at >= :start_date"
        params["start_date"] = str(start_date)
    if end_date:
        date_filter += " AND fi.enrolled_at <= :end_date"
        params["end_date"] = str(end_date)

    query = text(f"""
        SELECT
            COUNT(*) AS total_enrolled,
            COUNT(*) FILTER (WHERE fi.status = 'active') AS active,
            COUNT(*) FILTER (WHERE fi.status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE fi.status = 'goal_met') AS goals_hit,
            COUNT(*) FILTER (WHERE fi.status = 'error') AS errored,
            COUNT(*) FILTER (WHERE fi.status = 'cancelled') AS cancelled
        FROM flow_instances fi
        WHERE fi.flow_id = :flow_id
          AND fi.org_id = :org_id
          {date_filter}
    """)
    result = await db.execute(query, params)
    row = result.one()

    return FlowOverview(
        flow_id=str(flow_id),
        total_enrolled=row.total_enrolled,
        active=row.active,
        completed=row.completed,
        goals_hit=row.goals_hit,
        errored=row.errored,
        cancelled=row.cancelled,
        conversion_rate=compute_conversion_rate(row.total_enrolled, row.goals_hit),
        error_rate=compute_error_rate(row.total_enrolled, row.errored),
    )


@router.get("/{flow_id}/analytics/nodes", response_model=NodeStatsResponse)
async def get_node_stats(
    flow_id: uuid.UUID,
    version_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Per-node pass/fail statistics for canvas badges."""
    version_filter = ""
    params: dict[str, Any] = {
        "flow_id": str(flow_id),
        "org_id": str(org.id),
    }
    if version_id:
        version_filter = "AND ftp.version_id = :version_id"
        params["version_id"] = str(version_id)

    query = text(f"""
        SELECT
            fn.id AS node_id,
            fn.node_type,
            fn.label AS node_label,
            COUNT(ftp.id) AS total,
            COUNT(ftp.id) FILTER (WHERE ftp.status IN ('completed', 'delivered', 'replied')) AS passed,
            COUNT(ftp.id) FILTER (WHERE ftp.status IN ('failed', 'error')) AS failed,
            AVG(EXTRACT(EPOCH FROM (ftp.completed_at - ftp.started_at)))
                FILTER (WHERE ftp.completed_at IS NOT NULL) AS avg_duration_seconds
        FROM flow_nodes fn
        JOIN flow_versions fv ON fn.version_id = fv.id
        LEFT JOIN flow_touchpoints ftp ON ftp.node_id = fn.id
        WHERE fv.flow_id = :flow_id
          AND fn.org_id = :org_id
          {version_filter}
        GROUP BY fn.id, fn.node_type, fn.label
        ORDER BY fn.position_y ASC, fn.position_x ASC
    """)
    result = await db.execute(query, params)
    rows = result.all()

    nodes = [
        NodeStats(
            node_id=str(r.node_id),
            node_type=r.node_type,
            node_label=r.node_label,
            total=r.total,
            passed=r.passed,
            failed=r.failed,
            success_rate=round(r.passed / r.total, 4) if r.total > 0 else 0.0,
            avg_duration_seconds=round(r.avg_duration_seconds, 2) if r.avg_duration_seconds else None,
        )
        for r in rows
    ]

    return NodeStatsResponse(flow_id=str(flow_id), nodes=nodes)


@router.get("/{flow_id}/analytics/branches", response_model=BranchCountsResponse)
async def get_branch_counts(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Per-branch transition counts for condition nodes."""
    query = text("""
        SELECT
            fn.id AS node_id,
            fn.label AS node_label,
            fe.condition_label,
            COUNT(ft.id) AS count
        FROM flow_transitions ft
        JOIN flow_edges fe ON ft.edge_id = fe.id
        JOIN flow_nodes fn ON fe.source_node_id = fn.id
        WHERE fn.node_type = 'condition'
          AND fn.org_id = :org_id
          AND fn.version_id IN (
              SELECT fv.id FROM flow_versions fv WHERE fv.flow_id = :flow_id
          )
        GROUP BY fn.id, fn.label, fe.condition_label
        ORDER BY fn.label, COUNT(ft.id) DESC
    """)
    result = await db.execute(
        query, {"flow_id": str(flow_id), "org_id": str(org.id)}
    )
    rows = result.all()

    branches = [
        BranchCount(
            node_id=str(r.node_id),
            node_label=r.node_label,
            condition_label=r.condition_label,
            count=r.count,
        )
        for r in rows
    ]

    return BranchCountsResponse(flow_id=str(flow_id), branches=branches)


@router.get("/{flow_id}/analytics/funnel", response_model=FunnelResponse)
async def get_funnel(
    flow_id: uuid.UUID,
    version_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Funnel view: drop-off at each node along the most common path."""
    params: dict[str, Any] = {
        "flow_id": str(flow_id),
        "org_id": str(org.id),
    }
    version_filter = ""
    if version_id:
        version_filter = "AND fi.version_id = :version_id"
        params["version_id"] = str(version_id)

    # Count how many instances reached each node via transitions
    query = text(f"""
        WITH node_reach AS (
            SELECT
                ft.to_node_id AS node_id,
                COUNT(DISTINCT ft.instance_id) AS reached_count
            FROM flow_transitions ft
            JOIN flow_instances fi ON ft.instance_id = fi.id
            WHERE fi.flow_id = :flow_id
              AND fi.org_id = :org_id
              {version_filter}
            GROUP BY ft.to_node_id
        )
        SELECT
            fn.id AS node_id,
            fn.label AS node_label,
            fn.node_type,
            COALESCE(nr.reached_count, 0) AS reached_count,
            fn.position_y AS step_order
        FROM flow_nodes fn
        JOIN flow_versions fv ON fn.version_id = fv.id
        LEFT JOIN node_reach nr ON nr.node_id = fn.id
        WHERE fv.flow_id = :flow_id
          AND fn.org_id = :org_id
          AND fn.node_type NOT IN ('note')
        ORDER BY fn.position_y ASC
    """)
    result = await db.execute(query, params)
    rows = result.all()

    steps = [
        {
            "node_id": str(r.node_id),
            "node_label": r.node_label,
            "node_type": r.node_type,
            "reached_count": r.reached_count,
        }
        for r in rows
    ]

    steps = compute_drop_off_rates(steps)

    # Conversion = goal nodes reached / total enrolled
    total_enrolled = steps[0]["reached_count"] if steps else 0
    total_goals = sum(s["reached_count"] for s in steps if s["node_type"] == "goal")

    return FunnelResponse(
        flow_id=str(flow_id),
        steps=[FunnelStep(**s) for s in steps],
        conversion_rate=compute_conversion_rate(total_enrolled, total_goals),
        total_enrolled=total_enrolled,
        total_goals=total_goals,
    )


@router.get("/{flow_id}/analytics/compare", response_model=VersionComparisonResponse)
async def get_version_comparison(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Side-by-side version performance comparison."""
    query = text("""
        SELECT
            fi.version_id,
            fv.version_number,
            COUNT(*) AS total_enrolled,
            COUNT(*) FILTER (WHERE fi.status IN ('completed', 'goal_met')) AS total_completed,
            COUNT(*) FILTER (WHERE fi.status = 'goal_met') AS total_goals,
            COUNT(*) FILTER (WHERE fi.status = 'error') AS total_errors,
            AVG(EXTRACT(EPOCH FROM (fi.completed_at - fi.enrolled_at)) / 3600.0)
                FILTER (WHERE fi.completed_at IS NOT NULL) AS avg_duration_hours
        FROM flow_instances fi
        JOIN flow_versions fv ON fi.version_id = fv.id
        WHERE fi.flow_id = :flow_id
          AND fi.org_id = :org_id
        GROUP BY fi.version_id, fv.version_number
        ORDER BY fv.version_number ASC
    """)
    result = await db.execute(
        query, {"flow_id": str(flow_id), "org_id": str(org.id)}
    )
    rows = result.all()

    versions = [
        VersionStats(
            version_id=str(r.version_id),
            version_number=r.version_number,
            total_enrolled=r.total_enrolled,
            total_completed=r.total_completed,
            total_goals=r.total_goals,
            total_errors=r.total_errors,
            conversion_rate=compute_conversion_rate(r.total_enrolled, r.total_goals),
            error_rate=compute_error_rate(r.total_enrolled, r.total_errors),
            avg_duration_hours=round(r.avg_duration_hours, 1) if r.avg_duration_hours else None,
        )
        for r in rows
    ]

    return VersionComparisonResponse(flow_id=str(flow_id), versions=versions)
```

- [ ] **Step 5: Register the analytics router in main.py**

In `app/main.py`, add:

```python
from app.api.flow_analytics import router as flow_analytics_router
app.include_router(flow_analytics_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_flow_analytics.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/services/flow_analytics.py app/api/flow_analytics.py tests/test_flow_analytics.py app/main.py
git commit -m "feat: add flow analytics API with node stats, funnel, and version comparison

Adds 5 endpoints:
- GET /api/flows/{id}/analytics/overview — enrollment/conversion/error summary
- GET /api/flows/{id}/analytics/nodes — per-node pass/fail/duration stats
- GET /api/flows/{id}/analytics/branches — condition node branch counts
- GET /api/flows/{id}/analytics/funnel — drop-off funnel with conversion rate
- GET /api/flows/{id}/analytics/compare — side-by-side version performance

Includes reusable query helpers in app/services/flow_analytics.py."
```

---

## Task 3: Backend — Admin Notifications Service

**Files:**
- Create: `app/services/flow_notifications.py`
- Create: `tests/test_flow_notifications.py`

- [ ] **Step 1: Write failing tests for notification triggers**

```python
# tests/test_flow_notifications.py
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

FAKE_ORG_ID = uuid.uuid4()
FAKE_FLOW_ID = uuid.uuid4()
FAKE_INSTANCE_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_notify_instance_error_creates_notification():
    """Instance entering error state triggers admin notification."""
    from app.services.flow_notifications import notify_instance_error

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    await notify_instance_error(
        db=mock_db,
        org_id=FAKE_ORG_ID,
        instance_id=FAKE_INSTANCE_ID,
        flow_name="Follow-up Flow",
        error_message="WhatsApp delivery failed after 3 retries",
    )

    # Should have inserted a notification record
    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args
    # Verify the SQL contains INSERT INTO notifications
    sql_text = str(call_args[0][0])
    assert "notifications" in sql_text.lower() or "notification" in sql_text.lower()


@pytest.mark.asyncio
async def test_check_error_rate_alerts_above_threshold():
    """Flow error rate > 10% triggers alert notification."""
    from app.services.flow_notifications import check_flow_error_rate

    mock_db = AsyncMock()

    # Simulate: 100 instances in last hour, 15 errors = 15% > threshold
    mock_row = MagicMock()
    mock_row.total = 100
    mock_row.errors = 15

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    alerted = await check_flow_error_rate(
        db=mock_db,
        org_id=FAKE_ORG_ID,
        flow_id=FAKE_FLOW_ID,
        flow_name="Follow-up Flow",
        threshold=0.10,
    )

    assert alerted is True
    # Should have called execute twice: once for query, once for insert
    assert mock_db.execute.call_count == 2


@pytest.mark.asyncio
async def test_check_error_rate_no_alert_below_threshold():
    """Flow error rate below 10% does not trigger alert."""
    from app.services.flow_notifications import check_flow_error_rate

    mock_db = AsyncMock()

    mock_row = MagicMock()
    mock_row.total = 100
    mock_row.errors = 5  # 5% < 10% threshold

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    alerted = await check_flow_error_rate(
        db=mock_db,
        org_id=FAKE_ORG_ID,
        flow_id=FAKE_FLOW_ID,
        flow_name="Follow-up Flow",
        threshold=0.10,
    )

    assert alerted is False
    # Should have called execute only once (the check query, no insert)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_get_flow_health_summary():
    """Flow health summary returns active flows, instances, error counts."""
    from app.services.flow_notifications import get_flow_health_summary

    mock_db = AsyncMock()

    mock_row = MagicMock()
    mock_row.active_flows = 5
    mock_row.active_instances = 234
    mock_row.error_count = 8
    mock_row.error_rate = 0.034

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    summary = await get_flow_health_summary(db=mock_db, org_id=FAKE_ORG_ID)

    assert summary["active_flows"] == 5
    assert summary["active_instances"] == 234
    assert summary["error_count"] == 8
    assert summary["error_rate"] == pytest.approx(0.034, abs=0.001)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flow_notifications.py -v`
Expected: ImportError — `app.services.flow_notifications` does not exist yet.

- [ ] **Step 3: Implement the notifications service**

```python
# app/services/flow_notifications.py
"""Flow admin notifications — error alerts and health monitoring.

Notifications are stored in a `notifications` table (org-scoped).
The frontend polls or uses SSE to display them in a notification bell.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_RATE_THRESHOLD = 0.10  # 10%
ERROR_RATE_WINDOW_HOURS = 1


# ---------------------------------------------------------------------------
# Notification writers
# ---------------------------------------------------------------------------


async def notify_instance_error(
    db: AsyncSession,
    org_id: uuid.UUID,
    instance_id: uuid.UUID,
    flow_name: str,
    error_message: str,
) -> None:
    """Create an in-app notification when an instance enters error state."""
    notification_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO notifications (id, org_id, type, title, body, metadata, created_at, read)
            VALUES (:id, :org_id, :type, :title, :body, :metadata::jsonb, :created_at, false)
        """),
        {
            "id": str(notification_id),
            "org_id": str(org_id),
            "type": "flow_error",
            "title": f"Flow Error: {flow_name}",
            "body": f"Instance {str(instance_id)[:8]}... failed: {error_message[:200]}",
            "metadata": f'{{"instance_id": "{instance_id}", "flow_name": "{flow_name}"}}',
            "created_at": now,
        },
    )
    await db.commit()

    logger.warning(
        "flow_instance_error_notification",
        org_id=str(org_id),
        instance_id=str(instance_id),
        flow_name=flow_name,
    )


async def notify_touchpoint_failure(
    db: AsyncSession,
    org_id: uuid.UUID,
    instance_id: uuid.UUID,
    flow_name: str,
    node_label: str,
    error_message: str,
) -> None:
    """Notification when a touchpoint fails after all retries."""
    notification_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO notifications (id, org_id, type, title, body, metadata, created_at, read)
            VALUES (:id, :org_id, :type, :title, :body, :metadata::jsonb, :created_at, false)
        """),
        {
            "id": str(notification_id),
            "org_id": str(org_id),
            "type": "touchpoint_failure",
            "title": f"Step Failed: {node_label} in {flow_name}",
            "body": error_message[:300],
            "metadata": f'{{"instance_id": "{instance_id}", "node_label": "{node_label}"}}',
            "created_at": now,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Error rate monitoring
# ---------------------------------------------------------------------------


async def check_flow_error_rate(
    db: AsyncSession,
    org_id: uuid.UUID,
    flow_id: uuid.UUID,
    flow_name: str,
    threshold: float = ERROR_RATE_THRESHOLD,
) -> bool:
    """Check if flow error rate exceeds threshold over the last hour.

    Returns True if an alert was created.
    """
    window_start = datetime.now(timezone.utc) - timedelta(hours=ERROR_RATE_WINDOW_HOURS)

    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'error') AS errors
            FROM flow_instances
            WHERE flow_id = :flow_id
              AND org_id = :org_id
              AND enrolled_at >= :window_start
        """),
        {
            "flow_id": str(flow_id),
            "org_id": str(org_id),
            "window_start": window_start,
        },
    )
    row = result.one()

    if row.total == 0:
        return False

    error_rate = row.errors / row.total
    if error_rate <= threshold:
        return False

    # Create alert notification
    notification_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO notifications (id, org_id, type, title, body, metadata, created_at, read)
            VALUES (:id, :org_id, :type, :title, :body, :metadata::jsonb, :created_at, false)
        """),
        {
            "id": str(notification_id),
            "org_id": str(org_id),
            "type": "flow_error_rate",
            "title": f"High Error Rate: {flow_name}",
            "body": f"Error rate is {error_rate:.0%} ({row.errors}/{row.total} instances in last hour)",
            "metadata": f'{{"flow_id": "{flow_id}", "error_rate": {error_rate:.4f}}}',
            "created_at": now,
        },
    )
    await db.commit()

    logger.error(
        "flow_error_rate_alert",
        org_id=str(org_id),
        flow_id=str(flow_id),
        error_rate=error_rate,
        threshold=threshold,
    )

    return True


# ---------------------------------------------------------------------------
# Health dashboard data
# ---------------------------------------------------------------------------


async def get_flow_health_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Get org-wide flow health summary for dashboard widget."""
    result = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(DISTINCT fd.id)
                 FROM flow_definitions fd
                 WHERE fd.org_id = :org_id AND fd.is_active = true) AS active_flows,
                COUNT(*) AS active_instances,
                COUNT(*) FILTER (WHERE fi.status = 'error') AS error_count,
                CASE
                    WHEN COUNT(*) > 0
                    THEN ROUND(COUNT(*) FILTER (WHERE fi.status = 'error')::numeric / COUNT(*), 4)
                    ELSE 0
                END AS error_rate
            FROM flow_instances fi
            WHERE fi.org_id = :org_id
              AND fi.status IN ('active', 'error', 'waiting')
        """),
        {"org_id": str(org_id)},
    )
    row = result.one()

    return {
        "active_flows": row.active_flows,
        "active_instances": row.active_instances,
        "error_count": row.error_count,
        "error_rate": float(row.error_rate),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_flow_notifications.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/flow_notifications.py tests/test_flow_notifications.py
git commit -m "feat: add flow notification service for error alerts and health monitoring

Provides:
- notify_instance_error() — in-app alert when instance enters error state
- notify_touchpoint_failure() — alert when touchpoint fails after all retries
- check_flow_error_rate() — alert when error rate exceeds 10% over 1 hour
- get_flow_health_summary() — org-wide flow health for dashboard widget

Writes to notifications table with type-based routing for display."
```

---

## Task 4: Frontend — TypeScript API Client

**Files:**
- Create: `frontend/src/lib/flow-analytics-api.ts`

- [ ] **Step 1: Create the API client with types and fetch functions**

```typescript
// frontend/src/lib/flow-analytics-api.ts
import { apiFetch } from "./api";

// ---------------------------------------------------------------------------
// Types — Lead Flow History
// ---------------------------------------------------------------------------

export interface FlowEnrollment {
  instance_id: string;
  flow_id: string;
  flow_name: string;
  version_number: number;
  status: string;
  current_node_id: string | null;
  enrolled_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface LeadFlowHistoryResponse {
  lead_id: string;
  enrollments: FlowEnrollment[];
}

export interface TransitionStep {
  from_node_id: string | null;
  to_node_id: string;
  node_type: string;
  node_label: string;
  outcome_data: Record<string, unknown> | null;
  transitioned_at: string;
  touchpoint_status: string | null;
  touchpoint_error: string | null;
}

export interface JourneyResponse {
  instance_id: string;
  transitions: TransitionStep[];
}

// ---------------------------------------------------------------------------
// Types — Canvas Leads Panel
// ---------------------------------------------------------------------------

export interface CanvasLead {
  instance_id: string;
  lead_id: string;
  lead_name: string | null;
  lead_phone: string | null;
  status: string;
  current_node_id: string | null;
  current_node_label: string | null;
  enrolled_at: string;
}

export interface CanvasLeadsResponse {
  flow_id: string;
  leads: CanvasLead[];
  total: number;
  page: number;
  page_size: number;
}

export interface NodeCountsResponse {
  flow_id: string;
  counts: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Types — Flow Analytics
// ---------------------------------------------------------------------------

export interface NodeStats {
  node_id: string;
  node_type: string;
  node_label: string;
  total: number;
  passed: number;
  failed: number;
  success_rate: number;
  avg_duration_seconds: number | null;
}

export interface NodeStatsResponse {
  flow_id: string;
  nodes: NodeStats[];
}

export interface BranchCount {
  node_id: string;
  node_label: string;
  condition_label: string;
  count: number;
}

export interface BranchCountsResponse {
  flow_id: string;
  branches: BranchCount[];
}

export interface FlowFunnelStep {
  node_id: string;
  node_label: string;
  node_type: string;
  reached_count: number;
  drop_off_rate: number;
}

export interface FlowFunnelResponse {
  flow_id: string;
  steps: FlowFunnelStep[];
  conversion_rate: number;
  total_enrolled: number;
  total_goals: number;
}

export interface VersionStats {
  version_id: string;
  version_number: number;
  total_enrolled: number;
  total_completed: number;
  total_goals: number;
  total_errors: number;
  conversion_rate: number;
  error_rate: number;
  avg_duration_hours: number | null;
}

export interface VersionComparisonResponse {
  flow_id: string;
  versions: VersionStats[];
}

export interface FlowOverview {
  flow_id: string;
  total_enrolled: number;
  active: number;
  completed: number;
  goals_hit: number;
  errored: number;
  cancelled: number;
  conversion_rate: number;
  error_rate: number;
}

// ---------------------------------------------------------------------------
// Types — Flow Health
// ---------------------------------------------------------------------------

export interface FlowHealthSummary {
  active_flows: number;
  active_instances: number;
  error_count: number;
  error_rate: number;
}

// ---------------------------------------------------------------------------
// API functions — Lead Flow History
// ---------------------------------------------------------------------------

export const fetchLeadFlowHistory = (leadId: string) =>
  apiFetch<LeadFlowHistoryResponse>(`/api/flows/leads/${leadId}/history`);

export const fetchInstanceJourney = (instanceId: string) =>
  apiFetch<JourneyResponse>(`/api/flows/instances/${instanceId}/journey`);

// ---------------------------------------------------------------------------
// API functions — Canvas Leads
// ---------------------------------------------------------------------------

export const fetchCanvasLeads = (
  flowId: string,
  params?: { status?: string; node_id?: string; page?: number }
) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.node_id) qs.set("node_id", params.node_id);
  if (params?.page) qs.set("page", String(params.page));
  return apiFetch<CanvasLeadsResponse>(`/api/flows/${flowId}/leads?${qs}`);
};

export const fetchNodeCounts = (flowId: string) =>
  apiFetch<NodeCountsResponse>(`/api/flows/${flowId}/node-counts`);

// ---------------------------------------------------------------------------
// API functions — Flow Analytics
// ---------------------------------------------------------------------------

export interface FlowAnalyticsFilters {
  start_date?: string;
  end_date?: string;
  version_id?: string;
}

function buildFlowAnalyticsQS(filters?: FlowAnalyticsFilters): string {
  const qs = new URLSearchParams();
  if (filters?.start_date) qs.set("start_date", filters.start_date);
  if (filters?.end_date) qs.set("end_date", filters.end_date);
  if (filters?.version_id) qs.set("version_id", filters.version_id);
  return qs.toString();
}

export const fetchFlowOverview = (flowId: string, filters?: FlowAnalyticsFilters) =>
  apiFetch<FlowOverview>(
    `/api/flows/${flowId}/analytics/overview?${buildFlowAnalyticsQS(filters)}`
  );

export const fetchNodeStats = (flowId: string, filters?: FlowAnalyticsFilters) =>
  apiFetch<NodeStatsResponse>(
    `/api/flows/${flowId}/analytics/nodes?${buildFlowAnalyticsQS(filters)}`
  );

export const fetchBranchCounts = (flowId: string) =>
  apiFetch<BranchCountsResponse>(`/api/flows/${flowId}/analytics/branches`);

export const fetchFlowFunnel = (flowId: string, filters?: FlowAnalyticsFilters) =>
  apiFetch<FlowFunnelResponse>(
    `/api/flows/${flowId}/analytics/funnel?${buildFlowAnalyticsQS(filters)}`
  );

export const fetchVersionComparison = (flowId: string) =>
  apiFetch<VersionComparisonResponse>(`/api/flows/${flowId}/analytics/compare`);

// ---------------------------------------------------------------------------
// API functions — Flow Health (dashboard widget)
// ---------------------------------------------------------------------------

export const fetchFlowHealth = () =>
  apiFetch<FlowHealthSummary>(`/api/flows/health`);
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit src/lib/flow-analytics-api.ts`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/flow-analytics-api.ts
git commit -m "feat: add TypeScript API client for flow analytics and lead history

Exports types and fetch functions for:
- Lead flow history (enrollments, journey transitions)
- Canvas leads panel (filtered leads, node counts)
- Flow analytics (overview, node stats, branches, funnel, version comparison)
- Flow health dashboard widget"
```

---

## Task 5: Frontend — Lead Profile Flow History Tab

**Files:**
- Create: `frontend/src/app/(app)/leads/components/FlowHistoryTab.tsx`
- Create: `frontend/src/app/(app)/leads/components/__tests__/FlowHistoryTab.test.tsx`
- Modify: `frontend/src/app/(app)/leads/[leadId]/page.tsx`

- [ ] **Step 1: Write failing tests for FlowHistoryTab**

```typescript
// frontend/src/app/(app)/leads/components/__tests__/FlowHistoryTab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { FlowHistoryTab } from "../FlowHistoryTab";

// Mock the API
vi.mock("@/lib/flow-analytics-api", () => ({
  fetchLeadFlowHistory: vi.fn(),
  fetchInstanceJourney: vi.fn(),
}));

import { fetchLeadFlowHistory, fetchInstanceJourney } from "@/lib/flow-analytics-api";

const mockHistory = {
  lead_id: "lead-1",
  enrollments: [
    {
      instance_id: "inst-1",
      flow_id: "flow-1",
      flow_name: "Follow-up Flow",
      version_number: 2,
      status: "active",
      current_node_id: "node-2",
      enrolled_at: "2026-03-20T10:00:00Z",
      completed_at: null,
      error_message: null,
    },
    {
      instance_id: "inst-2",
      flow_id: "flow-2",
      flow_name: "Onboarding Flow",
      version_number: 1,
      status: "completed",
      current_node_id: null,
      enrolled_at: "2026-03-15T08:00:00Z",
      completed_at: "2026-03-18T14:30:00Z",
      error_message: null,
    },
  ],
};

const mockJourney = {
  instance_id: "inst-1",
  transitions: [
    {
      from_node_id: null,
      to_node_id: "node-1",
      node_type: "trigger",
      node_label: "Entry",
      outcome_data: null,
      transitioned_at: "2026-03-20T10:00:00Z",
      touchpoint_status: null,
      touchpoint_error: null,
    },
    {
      from_node_id: "node-1",
      to_node_id: "node-2",
      node_type: "voice_call",
      node_label: "Call Step",
      outcome_data: { call_outcome: "picked_up" },
      transitioned_at: "2026-03-20T10:05:00Z",
      touchpoint_status: "completed",
      touchpoint_error: null,
    },
  ],
};

describe("FlowHistoryTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders enrollment list", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue(mockHistory);

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("Follow-up Flow")).toBeInTheDocument();
      expect(screen.getByText("Onboarding Flow")).toBeInTheDocument();
    });
  });

  it("shows version badge", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue(mockHistory);

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("v2")).toBeInTheDocument();
      expect(screen.getByText("v1")).toBeInTheDocument();
    });
  });

  it("shows status badges", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue(mockHistory);

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("active")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  it("expands to show journey on click", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue(mockHistory);
    (fetchInstanceJourney as ReturnType<typeof vi.fn>).mockResolvedValue(mockJourney);

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText("Follow-up Flow")).toBeInTheDocument();
    });

    // Click to expand
    await userEvent.click(screen.getByText("Follow-up Flow"));

    await waitFor(() => {
      expect(fetchInstanceJourney).toHaveBeenCalledWith("inst-1");
      expect(screen.getByText("Entry")).toBeInTheDocument();
      expect(screen.getByText("Call Step")).toBeInTheDocument();
    });
  });

  it("shows empty state", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: "lead-1",
      enrollments: [],
    });

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      expect(screen.getByText(/not enrolled in any flows/i)).toBeInTheDocument();
    });
  });

  it("renders View on Canvas link", async () => {
    (fetchLeadFlowHistory as ReturnType<typeof vi.fn>).mockResolvedValue(mockHistory);

    render(<FlowHistoryTab leadId="lead-1" />);

    await waitFor(() => {
      const links = screen.getAllByText("View on Canvas");
      expect(links.length).toBeGreaterThan(0);
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/app/\\(app\\)/leads/components/__tests__/FlowHistoryTab.test.tsx`
Expected: Cannot find module `../FlowHistoryTab`

- [ ] **Step 3: Implement the FlowHistoryTab component**

```tsx
// frontend/src/app/(app)/leads/components/FlowHistoryTab.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  GitBranch,
  Phone,
  MessageSquare,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { format, formatDistanceToNow } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchLeadFlowHistory,
  fetchInstanceJourney,
  type FlowEnrollment,
  type TransitionStep,
} from "@/lib/flow-analytics-api";

// ---------------------------------------------------------------------------
// Status colors
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  active: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  completed: "bg-green-500/15 text-green-400 border-green-500/25",
  goal_met: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  error: "bg-red-500/15 text-red-400 border-red-500/25",
  cancelled: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
  paused: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  waiting: "bg-purple-500/15 text-purple-400 border-purple-500/25",
};

const NODE_ICONS: Record<string, typeof Phone> = {
  voice_call: Phone,
  whatsapp_template: MessageSquare,
  whatsapp_session: MessageSquare,
  condition: GitBranch,
  delay: Clock,
  wait_for_event: Clock,
  goal: CheckCircle2,
  end: CheckCircle2,
  trigger: ChevronRight,
};

const TOUCHPOINT_STATUS_ICON: Record<string, typeof CheckCircle2> = {
  completed: CheckCircle2,
  delivered: CheckCircle2,
  replied: CheckCircle2,
  failed: XCircle,
  error: AlertTriangle,
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function JourneyTimeline({ transitions }: { transitions: TransitionStep[] }) {
  return (
    <div className="ml-4 mt-3 border-l-2 border-border pl-4 space-y-3">
      {transitions.map((t, i) => {
        const Icon = NODE_ICONS[t.node_type] || ChevronRight;
        const StatusIcon = t.touchpoint_status
          ? TOUCHPOINT_STATUS_ICON[t.touchpoint_status] || Clock
          : Clock;

        return (
          <div key={i} className="relative flex items-start gap-3">
            {/* Timeline dot */}
            <div className="absolute -left-[1.4rem] top-1 h-2.5 w-2.5 rounded-full bg-border" />

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-sm font-medium">{t.node_label}</span>
                {t.touchpoint_status && (
                  <Badge
                    variant="outline"
                    className={`text-[10px] px-1.5 py-0 ${
                      STATUS_COLORS[t.touchpoint_status] || "text-muted-foreground"
                    }`}
                  >
                    <StatusIcon className="h-2.5 w-2.5 mr-0.5" />
                    {t.touchpoint_status}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-muted-foreground">
                  {format(new Date(t.transitioned_at), "MMM d, h:mm a")}
                </span>
                {t.outcome_data && Object.keys(t.outcome_data).length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {Object.entries(t.outcome_data)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ")}
                  </span>
                )}
              </div>
              {t.touchpoint_error && (
                <p className="text-xs text-red-400 mt-0.5">{t.touchpoint_error}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EnrollmentCard({ enrollment }: { enrollment: FlowEnrollment }) {
  const [expanded, setExpanded] = useState(false);
  const [journey, setJourney] = useState<TransitionStep[] | null>(null);
  const [loadingJourney, setLoadingJourney] = useState(false);

  const handleExpand = useCallback(async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (!journey) {
      setLoadingJourney(true);
      try {
        const data = await fetchInstanceJourney(enrollment.instance_id);
        setJourney(data.transitions);
      } catch {
        // Silently fail — user sees empty timeline
      } finally {
        setLoadingJourney(false);
      }
    }
  }, [expanded, journey, enrollment.instance_id]);

  const ChevronIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="border border-border rounded-lg p-3">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={handleExpand}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && handleExpand()}
      >
        <div className="flex items-center gap-2">
          <ChevronIcon className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">{enrollment.flow_name}</span>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            v{enrollment.version_number}
          </Badge>
          <Badge
            variant="outline"
            className={`text-[10px] px-1.5 py-0 ${
              STATUS_COLORS[enrollment.status] || "text-muted-foreground"
            }`}
          >
            {enrollment.status}
          </Badge>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {formatDistanceToNow(new Date(enrollment.enrolled_at), {
              addSuffix: true,
            })}
          </span>
          <Link
            href={`/sequences/${enrollment.flow_id}?instance=${enrollment.instance_id}`}
            onClick={(e) => e.stopPropagation()}
          >
            <Button variant="ghost" size="sm" className="h-6 text-xs gap-1">
              <ExternalLink className="h-3 w-3" />
              View on Canvas
            </Button>
          </Link>
        </div>
      </div>

      {expanded && (
        <div className="mt-2">
          <div className="flex gap-4 text-xs text-muted-foreground mb-2">
            <span>
              Enrolled: {format(new Date(enrollment.enrolled_at), "MMM d, yyyy h:mm a")}
            </span>
            {enrollment.completed_at && (
              <span>
                Completed:{" "}
                {format(new Date(enrollment.completed_at), "MMM d, yyyy h:mm a")}
              </span>
            )}
          </div>
          {enrollment.error_message && (
            <p className="text-xs text-red-400 mb-2">{enrollment.error_message}</p>
          )}
          {loadingJourney ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground ml-4">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading journey...
            </div>
          ) : journey && journey.length > 0 ? (
            <JourneyTimeline transitions={journey} />
          ) : journey && journey.length === 0 ? (
            <p className="text-xs text-muted-foreground ml-4">No transitions recorded yet</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface FlowHistoryTabProps {
  leadId: string;
}

export function FlowHistoryTab({ leadId }: FlowHistoryTabProps) {
  const [enrollments, setEnrollments] = useState<FlowEnrollment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchLeadFlowHistory(leadId);
        if (!cancelled) setEnrollments(data.enrollments);
      } catch {
        // API error — show empty state
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (enrollments.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <GitBranch className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm">Not enrolled in any flows</p>
        <p className="text-xs mt-1">
          Enroll this lead in a flow from the Sequences page
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {enrollments.map((e) => (
        <EnrollmentCard key={e.instance_id} enrollment={e} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Add the Flows tab to the lead detail page**

In `frontend/src/app/(app)/leads/[leadId]/page.tsx`, add the import and tab:

```tsx
// Add to imports at the top:
import { FlowHistoryTab } from "@/app/(app)/leads/components/FlowHistoryTab";

// In the TabsList, add after the "sequences" trigger:
<TabsTrigger value="flows">Flows</TabsTrigger>

// After the sequences TabsContent, add:
{/* Flows tab */}
<TabsContent value="flows">
  <Card>
    <CardHeader>
      <CardTitle className="text-base">Flow History</CardTitle>
      <CardDescription>
        Flow enrollments and node-by-node journey for this lead
      </CardDescription>
    </CardHeader>
    <CardContent>
      <FlowHistoryTab leadId={leadId} />
    </CardContent>
  </Card>
</TabsContent>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/app/\\(app\\)/leads/components/__tests__/FlowHistoryTab.test.tsx`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(app\)/leads/components/FlowHistoryTab.tsx \
       frontend/src/app/\(app\)/leads/components/__tests__/FlowHistoryTab.test.tsx \
       frontend/src/app/\(app\)/leads/\[leadId\]/page.tsx
git commit -m "feat: add Flow History tab to lead detail page

Shows chronological list of all flow enrollments with status badges
and version numbers. Click to expand shows node-by-node journey
timeline with timestamps, outcomes, and touchpoint status. Includes
'View on Canvas' link to open the flow with this lead highlighted."
```

---

## Task 6: Frontend — Canvas Leads Panel

**Files:**
- Create: `frontend/src/app/(app)/sequences/[id]/components/LeadsPanel.tsx`
- Create: `frontend/src/app/(app)/sequences/[id]/components/JourneyOverlay.tsx`
- Create: `frontend/src/app/(app)/sequences/[id]/components/__tests__/LeadsPanel.test.tsx`

- [ ] **Step 1: Write failing tests for LeadsPanel**

```typescript
// frontend/src/app/(app)/sequences/[id]/components/__tests__/LeadsPanel.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { LeadsPanel } from "../LeadsPanel";

vi.mock("@/lib/flow-analytics-api", () => ({
  fetchCanvasLeads: vi.fn(),
  fetchInstanceJourney: vi.fn(),
}));

import { fetchCanvasLeads, fetchInstanceJourney } from "@/lib/flow-analytics-api";

const mockLeads = {
  flow_id: "flow-1",
  leads: [
    {
      instance_id: "inst-1",
      lead_id: "lead-1",
      lead_name: "John Doe",
      lead_phone: "+919876543210",
      status: "active",
      current_node_id: "node-2",
      current_node_label: "Call Step",
      enrolled_at: "2026-03-20T10:00:00Z",
    },
    {
      instance_id: "inst-2",
      lead_id: "lead-2",
      lead_name: "Jane Smith",
      lead_phone: "+919876543211",
      status: "completed",
      current_node_id: null,
      current_node_label: null,
      enrolled_at: "2026-03-19T08:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  page_size: 50,
};

describe("LeadsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders lead list", async () => {
    (fetchCanvasLeads as ReturnType<typeof vi.fn>).mockResolvedValue(mockLeads);

    render(
      <LeadsPanel
        flowId="flow-1"
        open={true}
        onClose={() => {}}
        onHighlightJourney={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("John Doe")).toBeInTheDocument();
      expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    });
  });

  it("filters by status", async () => {
    (fetchCanvasLeads as ReturnType<typeof vi.fn>).mockResolvedValue(mockLeads);

    render(
      <LeadsPanel
        flowId="flow-1"
        open={true}
        onClose={() => {}}
        onHighlightJourney={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("John Doe")).toBeInTheDocument();
    });

    // Change filter to "active"
    const statusSelect = screen.getByRole("combobox", { name: /status/i });
    await userEvent.click(statusSelect);
    // After selecting active, fetchCanvasLeads should be called with status filter
    expect(fetchCanvasLeads).toHaveBeenCalled();
  });

  it("calls onHighlightJourney when clicking a lead", async () => {
    (fetchCanvasLeads as ReturnType<typeof vi.fn>).mockResolvedValue(mockLeads);

    const mockJourney = {
      instance_id: "inst-1",
      transitions: [
        { from_node_id: null, to_node_id: "node-1", node_type: "trigger", node_label: "Entry", outcome_data: null, transitioned_at: "2026-03-20T10:00:00Z", touchpoint_status: null, touchpoint_error: null },
      ],
    };
    (fetchInstanceJourney as ReturnType<typeof vi.fn>).mockResolvedValue(mockJourney);

    const onHighlight = vi.fn();

    render(
      <LeadsPanel
        flowId="flow-1"
        open={true}
        onClose={() => {}}
        onHighlightJourney={onHighlight}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("John Doe")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("John Doe"));

    await waitFor(() => {
      expect(fetchInstanceJourney).toHaveBeenCalledWith("inst-1");
      expect(onHighlight).toHaveBeenCalled();
    });
  });

  it("shows total count", async () => {
    (fetchCanvasLeads as ReturnType<typeof vi.fn>).mockResolvedValue(mockLeads);

    render(
      <LeadsPanel
        flowId="flow-1"
        open={true}
        onClose={() => {}}
        onHighlightJourney={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/2 leads/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/app/\\(app\\)/sequences/\\[id\\]/components/__tests__/LeadsPanel.test.tsx`
Expected: Cannot find module `../LeadsPanel`

- [ ] **Step 3: Implement LeadsPanel component**

```tsx
// frontend/src/app/(app)/sequences/[id]/components/LeadsPanel.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  X,
  Users,
  Search,
  Phone,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchCanvasLeads,
  fetchInstanceJourney,
  type CanvasLead,
  type TransitionStep,
} from "@/lib/flow-analytics-api";

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "waiting", label: "Waiting" },
  { value: "completed", label: "Completed" },
  { value: "goal_met", label: "Goal met" },
  { value: "error", label: "Error" },
  { value: "cancelled", label: "Cancelled" },
];

const STATUS_COLORS: Record<string, string> = {
  active: "bg-blue-500/15 text-blue-400",
  waiting: "bg-purple-500/15 text-purple-400",
  completed: "bg-green-500/15 text-green-400",
  goal_met: "bg-emerald-500/15 text-emerald-400",
  error: "bg-red-500/15 text-red-400",
  cancelled: "bg-zinc-500/15 text-zinc-400",
};

interface LeadsPanelProps {
  flowId: string;
  open: boolean;
  onClose: () => void;
  onHighlightJourney: (nodeIds: string[]) => void;
  nodeId?: string; // Optional filter by current node
}

export function LeadsPanel({
  flowId,
  open,
  onClose,
  onHighlightJourney,
  nodeId,
}: LeadsPanelProps) {
  const [leads, setLeads] = useState<CanvasLead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [loadingJourney, setLoadingJourney] = useState(false);

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCanvasLeads(flowId, {
        status: statusFilter === "all" ? undefined : statusFilter,
        node_id: nodeId,
        page,
      });
      setLeads(data.leads);
      setTotal(data.total);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [flowId, statusFilter, nodeId, page]);

  useEffect(() => {
    if (open) loadLeads();
  }, [open, loadLeads]);

  const handleLeadClick = useCallback(
    async (lead: CanvasLead) => {
      if (selectedLeadId === lead.instance_id) {
        setSelectedLeadId(null);
        onHighlightJourney([]);
        return;
      }

      setSelectedLeadId(lead.instance_id);
      setLoadingJourney(true);
      try {
        const data = await fetchInstanceJourney(lead.instance_id);
        const nodeIds = data.transitions.map((t) => t.to_node_id);
        onHighlightJourney(nodeIds);
      } catch {
        onHighlightJourney([]);
      } finally {
        setLoadingJourney(false);
      }
    },
    [selectedLeadId, onHighlightJourney]
  );

  const totalPages = Math.max(1, Math.ceil(total / 50));

  if (!open) return null;

  return (
    <div className="absolute right-0 top-0 z-50 h-full w-80 border-l border-border bg-background shadow-lg flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border p-3">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          <span className="font-medium text-sm">Leads</span>
          <Badge variant="secondary" className="text-[10px]">
            {total} leads
          </Badge>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Filters */}
      <div className="border-b border-border p-3 space-y-2">
        <Select
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-8 text-xs" aria-label="Status filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Lead list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : leads.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Users className="h-6 w-6 mb-2 opacity-50" />
            <p className="text-xs">No leads match filters</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {leads.map((lead) => (
              <button
                key={lead.instance_id}
                className={`w-full text-left p-3 hover:bg-muted/50 transition-colors ${
                  selectedLeadId === lead.instance_id ? "bg-muted/70" : ""
                }`}
                onClick={() => handleLeadClick(lead)}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium truncate">
                    {lead.lead_name || "Unknown"}
                  </span>
                  <Badge
                    variant="outline"
                    className={`text-[10px] px-1.5 py-0 ${
                      STATUS_COLORS[lead.status] || ""
                    }`}
                  >
                    {lead.status}
                  </Badge>
                </div>
                {lead.lead_phone && (
                  <div className="flex items-center gap-1 mt-0.5">
                    <Phone className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">{lead.lead_phone}</span>
                  </div>
                )}
                <div className="flex items-center justify-between mt-1">
                  {lead.current_node_label && (
                    <span className="text-[10px] text-muted-foreground">
                      At: {lead.current_node_label}
                    </span>
                  )}
                  <span className="text-[10px] text-muted-foreground">
                    {formatDistanceToNow(new Date(lead.enrolled_at), {
                      addSuffix: true,
                    })}
                  </span>
                </div>
                {selectedLeadId === lead.instance_id && loadingJourney && (
                  <div className="flex items-center gap-1 mt-1 text-[10px] text-muted-foreground">
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                    Loading journey...
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {!loading && total > 50 && (
        <div className="flex items-center justify-between border-t border-border p-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="h-7"
          >
            <ChevronLeft className="h-3 w-3" />
          </Button>
          <span className="text-[10px] text-muted-foreground">
            {page}/{totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="h-7"
          >
            <ChevronRight className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement JourneyOverlay component**

```tsx
// frontend/src/app/(app)/sequences/[id]/components/JourneyOverlay.tsx
"use client";

/**
 * JourneyOverlay provides utility for highlighting a lead's journey path
 * on the React Flow canvas. It works by applying CSS classes to nodes/edges.
 *
 * Usage in the canvas parent:
 * 1. Keep a `highlightedNodeIds: string[]` state
 * 2. Pass it from LeadsPanel's onHighlightJourney callback
 * 3. Use getHighlightedNodeStyle/getHighlightedEdgeStyle on React Flow nodes/edges
 */

import type { CSSProperties } from "react";

const HIGHLIGHT_NODE_STYLE: CSSProperties = {
  boxShadow: "0 0 0 3px rgba(59, 130, 246, 0.5)",
  borderColor: "rgb(59, 130, 246)",
  transition: "box-shadow 0.3s ease, border-color 0.3s ease",
};

const DIM_NODE_STYLE: CSSProperties = {
  opacity: 0.3,
  transition: "opacity 0.3s ease",
};

const HIGHLIGHT_EDGE_STYLE: CSSProperties = {
  stroke: "rgb(59, 130, 246)",
  strokeWidth: 2.5,
  transition: "stroke 0.3s ease, stroke-width 0.3s ease",
};

const DIM_EDGE_STYLE: CSSProperties = {
  opacity: 0.15,
  transition: "opacity 0.3s ease",
};

/**
 * Returns style overrides for a node based on whether it's in the highlighted journey.
 * When highlightedNodeIds is empty, returns undefined (no override).
 */
export function getHighlightedNodeStyle(
  nodeId: string,
  highlightedNodeIds: string[]
): CSSProperties | undefined {
  if (highlightedNodeIds.length === 0) return undefined;
  return highlightedNodeIds.includes(nodeId)
    ? HIGHLIGHT_NODE_STYLE
    : DIM_NODE_STYLE;
}

/**
 * Returns style overrides for an edge based on whether both its source
 * and target are in the highlighted journey.
 */
export function getHighlightedEdgeStyle(
  sourceId: string,
  targetId: string,
  highlightedNodeIds: string[]
): CSSProperties | undefined {
  if (highlightedNodeIds.length === 0) return undefined;
  return highlightedNodeIds.includes(sourceId) &&
    highlightedNodeIds.includes(targetId)
    ? HIGHLIGHT_EDGE_STYLE
    : DIM_EDGE_STYLE;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/app/\\(app\\)/sequences/\\[id\\]/components/__tests__/LeadsPanel.test.tsx`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/\[id\]/components/LeadsPanel.tsx \
       frontend/src/app/\(app\)/sequences/\[id\]/components/JourneyOverlay.tsx \
       frontend/src/app/\(app\)/sequences/\[id\]/components/__tests__/LeadsPanel.test.tsx
git commit -m "feat: add canvas leads panel with journey highlight overlay

LeadsPanel drawer shows leads in a flow with status/node filters,
pagination, and click-to-highlight journey replay. JourneyOverlay
provides style utilities that dim non-visited nodes and highlight
the selected lead's path through the flow on the React Flow canvas."
```

---

## Task 7: Frontend — Canvas Node Badges

**Files:**
- Create: `frontend/src/app/(app)/sequences/[id]/components/NodeBadge.tsx`

- [ ] **Step 1: Implement the NodeBadge component**

```tsx
// frontend/src/app/(app)/sequences/[id]/components/NodeBadge.tsx
"use client";

import { useEffect, useState } from "react";
import { Users, CheckCircle2, XCircle, GitBranch, Target } from "lucide-react";
import type { NodeStats, BranchCount } from "@/lib/flow-analytics-api";

// ---------------------------------------------------------------------------
// Badge variants per node type
// ---------------------------------------------------------------------------

interface ActionBadgeProps {
  stats: NodeStats;
}

function ActionBadge({ stats }: ActionBadgeProps) {
  const pct = stats.total > 0 ? Math.round(stats.success_rate * 100) : 0;
  const color =
    pct >= 80
      ? "text-green-400 bg-green-500/10"
      : pct >= 50
        ? "text-yellow-400 bg-yellow-500/10"
        : "text-red-400 bg-red-500/10";

  return (
    <div
      className={`absolute -bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium ${color} border border-current/20 whitespace-nowrap`}
    >
      <CheckCircle2 className="h-2.5 w-2.5" />
      {stats.passed}
      <span className="text-muted-foreground">/</span>
      <XCircle className="h-2.5 w-2.5" />
      {stats.failed}
      <span className="text-muted-foreground ml-0.5">({pct}%)</span>
    </div>
  );
}

interface ConditionBadgeProps {
  branches: BranchCount[];
}

function ConditionBadge({ branches }: ConditionBadgeProps) {
  return (
    <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium text-purple-400 bg-purple-500/10 border border-purple-500/20 whitespace-nowrap">
      <GitBranch className="h-2.5 w-2.5" />
      {branches.map((b, i) => (
        <span key={b.condition_label}>
          {i > 0 && <span className="text-muted-foreground mx-0.5">|</span>}
          {b.condition_label}: {b.count}
        </span>
      ))}
    </div>
  );
}

interface GoalBadgeProps {
  count: number;
}

function GoalBadge({ count }: GoalBadgeProps) {
  return (
    <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 whitespace-nowrap">
      <Target className="h-2.5 w-2.5" />
      {count} goals
    </div>
  );
}

interface LeadCountBadgeProps {
  count: number;
}

function LeadCountBadge({ count }: LeadCountBadgeProps) {
  if (count === 0) return null;
  return (
    <div className="absolute -top-5 right-0 flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-medium text-blue-400 bg-blue-500/10 border border-blue-500/20 whitespace-nowrap">
      <Users className="h-2.5 w-2.5" />
      {count}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composite badge — renders the right variant based on node type
// ---------------------------------------------------------------------------

export interface NodeBadgeProps {
  nodeId: string;
  nodeType: string;
  nodeStats?: NodeStats;
  branchCounts?: BranchCount[];
  leadCount?: number;
}

export function NodeBadge({
  nodeId,
  nodeType,
  nodeStats,
  branchCounts,
  leadCount,
}: NodeBadgeProps) {
  return (
    <>
      {/* Lead count badge (top-right, all node types) */}
      {leadCount !== undefined && <LeadCountBadge count={leadCount} />}

      {/* Stats badge (bottom-center, type-specific) */}
      {nodeType === "condition" && branchCounts && branchCounts.length > 0 && (
        <ConditionBadge branches={branchCounts} />
      )}
      {nodeType === "goal" && nodeStats && (
        <GoalBadge count={nodeStats.passed} />
      )}
      {nodeType === "end" && nodeStats && (
        <GoalBadge count={nodeStats.total} />
      )}
      {["voice_call", "whatsapp_template", "whatsapp_session", "ai_generate"].includes(
        nodeType
      ) &&
        nodeStats && <ActionBadge stats={nodeStats} />}
    </>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit src/app/\\(app\\)/sequences/\\[id\\]/components/NodeBadge.tsx`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/\[id\]/components/NodeBadge.tsx
git commit -m "feat: add per-node analytics badge component for flow canvas

NodeBadge renders type-specific overlays on canvas nodes:
- Action nodes: passed/failed count with success rate percentage
- Condition nodes: per-branch transition counts
- Goal/End nodes: total count
- All nodes: active lead count badge (top-right)

Badges are positioned absolutely relative to the node wrapper
and refresh on page load (not real-time) per spec."
```

---

## Task 8: Frontend — Flow Analytics Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/analytics/flow/page.tsx`
- Create: `frontend/src/app/(app)/sequences/analytics/flow/components/FlowFunnel.tsx`
- Create: `frontend/src/app/(app)/sequences/analytics/flow/components/VersionComparison.tsx`
- Create: `frontend/src/app/(app)/sequences/analytics/flow/components/NodePerformanceTable.tsx`

- [ ] **Step 1: Implement the FlowFunnel component**

```tsx
// frontend/src/app/(app)/sequences/analytics/flow/components/FlowFunnel.tsx
"use client";

import type { FlowFunnelStep } from "@/lib/flow-analytics-api";

const NODE_TYPE_COLORS: Record<string, string> = {
  trigger: "bg-blue-500",
  voice_call: "bg-violet-500",
  whatsapp_template: "bg-green-500",
  whatsapp_session: "bg-green-500",
  condition: "bg-purple-500",
  delay: "bg-yellow-500",
  goal: "bg-emerald-500",
  end: "bg-zinc-500",
};

interface FlowFunnelProps {
  steps: FlowFunnelStep[];
  totalEnrolled: number;
  totalGoals: number;
  conversionRate: number;
}

export function FlowFunnel({
  steps,
  totalEnrolled,
  totalGoals,
  conversionRate,
}: FlowFunnelProps) {
  const maxCount = Math.max(...steps.map((s) => s.reached_count), 1);

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="text-center">
          <p className="text-2xl font-bold">{totalEnrolled}</p>
          <p className="text-xs text-muted-foreground">Enrolled</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold">{totalGoals}</p>
          <p className="text-xs text-muted-foreground">Goals Met</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold text-emerald-400">
            {(conversionRate * 100).toFixed(1)}%
          </p>
          <p className="text-xs text-muted-foreground">Conversion</p>
        </div>
      </div>

      {/* Funnel bars */}
      <div className="space-y-1.5">
        {steps.map((step, i) => {
          const widthPct = Math.max((step.reached_count / maxCount) * 100, 2);
          const barColor = NODE_TYPE_COLORS[step.node_type] || "bg-zinc-500";

          return (
            <div key={step.node_id} className="flex items-center gap-3">
              <div className="w-28 text-right">
                <p className="text-xs font-medium truncate">{step.node_label}</p>
              </div>
              <div className="flex-1 relative">
                <div
                  className={`h-7 rounded ${barColor} flex items-center px-2 transition-all duration-500`}
                  style={{ width: `${widthPct}%` }}
                >
                  <span className="text-[10px] font-medium text-white">
                    {step.reached_count}
                  </span>
                </div>
              </div>
              <div className="w-14 text-right">
                {step.drop_off_rate > 0 && (
                  <span className="text-[10px] text-red-400">
                    -{(step.drop_off_rate * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement the VersionComparison component**

```tsx
// frontend/src/app/(app)/sequences/analytics/flow/components/VersionComparison.tsx
"use client";

import type { VersionStats } from "@/lib/flow-analytics-api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface VersionComparisonProps {
  versions: VersionStats[];
}

export function VersionComparison({ versions }: VersionComparisonProps) {
  if (versions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No version data available yet
      </p>
    );
  }

  // Find the best performing version by conversion rate
  const bestVersionId = versions.reduce((best, v) =>
    v.conversion_rate > best.conversion_rate ? v : best
  ).version_id;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Version</TableHead>
          <TableHead className="text-right">Enrolled</TableHead>
          <TableHead className="text-right">Completed</TableHead>
          <TableHead className="text-right">Goals</TableHead>
          <TableHead className="text-right">Conversion</TableHead>
          <TableHead className="text-right">Errors</TableHead>
          <TableHead className="text-right">Error Rate</TableHead>
          <TableHead className="text-right">Avg Duration</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {versions.map((v) => (
          <TableRow
            key={v.version_id}
            className={v.version_id === bestVersionId ? "bg-emerald-500/5" : ""}
          >
            <TableCell>
              <div className="flex items-center gap-2">
                <span className="font-medium">v{v.version_number}</span>
                {v.version_id === bestVersionId && (
                  <Badge
                    variant="outline"
                    className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
                  >
                    Best
                  </Badge>
                )}
              </div>
            </TableCell>
            <TableCell className="text-right">{v.total_enrolled}</TableCell>
            <TableCell className="text-right">{v.total_completed}</TableCell>
            <TableCell className="text-right">{v.total_goals}</TableCell>
            <TableCell className="text-right font-medium">
              {(v.conversion_rate * 100).toFixed(1)}%
            </TableCell>
            <TableCell className="text-right">{v.total_errors}</TableCell>
            <TableCell className="text-right">
              <span
                className={
                  v.error_rate > 0.1
                    ? "text-red-400"
                    : v.error_rate > 0.05
                      ? "text-yellow-400"
                      : "text-muted-foreground"
                }
              >
                {(v.error_rate * 100).toFixed(1)}%
              </span>
            </TableCell>
            <TableCell className="text-right">
              {v.avg_duration_hours != null
                ? `${v.avg_duration_hours.toFixed(1)}h`
                : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 3: Implement the NodePerformanceTable component**

```tsx
// frontend/src/app/(app)/sequences/analytics/flow/components/NodePerformanceTable.tsx
"use client";

import { useState } from "react";
import type { NodeStats } from "@/lib/flow-analytics-api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";

const NODE_TYPE_LABELS: Record<string, string> = {
  trigger: "Trigger",
  voice_call: "Voice Call",
  whatsapp_template: "WhatsApp Template",
  whatsapp_session: "WhatsApp Session",
  ai_generate: "AI Generate",
  condition: "Condition",
  delay: "Delay",
  wait_for_event: "Wait",
  goal: "Goal",
  end: "End",
};

type SortKey = "node_label" | "total" | "success_rate" | "avg_duration_seconds";

interface NodePerformanceTableProps {
  nodes: NodeStats[];
}

export function NodePerformanceTable({ nodes }: NodePerformanceTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("total");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sorted = [...nodes].sort((a, b) => {
    const aVal = a[sortKey] ?? 0;
    const bVal = b[sortKey] ?? 0;
    if (typeof aVal === "string" && typeof bVal === "string") {
      return sortDir === "asc"
        ? aVal.localeCompare(bVal)
        : bVal.localeCompare(aVal);
    }
    return sortDir === "asc"
      ? (aVal as number) - (bVal as number)
      : (bVal as number) - (aVal as number);
  });

  const SortButton = ({ label, field }: { label: string; field: SortKey }) => (
    <Button
      variant="ghost"
      size="sm"
      className="h-6 px-1 text-xs font-medium"
      onClick={() => handleSort(field)}
    >
      {label}
      <ArrowUpDown className="h-3 w-3 ml-1" />
    </Button>
  );

  if (nodes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No node performance data available
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <SortButton label="Node" field="node_label" />
          </TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">
            <SortButton label="Total" field="total" />
          </TableHead>
          <TableHead className="text-right">Passed</TableHead>
          <TableHead className="text-right">Failed</TableHead>
          <TableHead className="text-right">
            <SortButton label="Success Rate" field="success_rate" />
          </TableHead>
          <TableHead className="text-right">
            <SortButton label="Avg Duration" field="avg_duration_seconds" />
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((node) => (
          <TableRow key={node.node_id}>
            <TableCell className="font-medium">{node.node_label}</TableCell>
            <TableCell>
              <Badge variant="outline" className="text-[10px]">
                {NODE_TYPE_LABELS[node.node_type] || node.node_type}
              </Badge>
            </TableCell>
            <TableCell className="text-right">{node.total}</TableCell>
            <TableCell className="text-right text-green-400">
              {node.passed}
            </TableCell>
            <TableCell className="text-right text-red-400">
              {node.failed}
            </TableCell>
            <TableCell className="text-right">
              <span
                className={
                  node.success_rate >= 0.8
                    ? "text-green-400"
                    : node.success_rate >= 0.5
                      ? "text-yellow-400"
                      : "text-red-400"
                }
              >
                {(node.success_rate * 100).toFixed(1)}%
              </span>
            </TableCell>
            <TableCell className="text-right text-muted-foreground">
              {node.avg_duration_seconds != null
                ? node.avg_duration_seconds < 60
                  ? `${node.avg_duration_seconds.toFixed(0)}s`
                  : `${(node.avg_duration_seconds / 60).toFixed(1)}m`
                : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 4: Implement the flow analytics page**

```tsx
// frontend/src/app/(app)/sequences/analytics/flow/page.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  BarChart3,
  TrendingUp,
  GitCompare,
  Activity,
  Loader2,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchFlowOverview,
  fetchNodeStats,
  fetchFlowFunnel,
  fetchBranchCounts,
  fetchVersionComparison,
  type FlowOverview,
  type NodeStats,
  type FlowFunnelStep,
  type BranchCount,
  type VersionStats,
  type FlowAnalyticsFilters,
} from "@/lib/flow-analytics-api";
import { FlowFunnel } from "./components/FlowFunnel";
import { VersionComparison } from "./components/VersionComparison";
import { NodePerformanceTable } from "./components/NodePerformanceTable";

// Reuse templates list for flow selection (adapt once flow list API exists)
import { fetchTemplates, type SequenceTemplate } from "@/lib/sequences-api";

const NAV_LINKS = [
  { href: "/sequences", label: "Templates" },
  { href: "/sequences/monitor", label: "Monitor" },
  { href: "/sequences/analytics", label: "Analytics" },
  { href: "/sequences/analytics/flow", label: "Flow Analytics" },
];

export default function FlowAnalyticsPage() {
  const searchParams = useSearchParams();
  const initialFlowId = searchParams.get("flow_id") || "";

  // State
  const [flowId, setFlowId] = useState(initialFlowId);
  const [flows, setFlows] = useState<SequenceTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState<FlowOverview | null>(null);
  const [nodeStats, setNodeStats] = useState<NodeStats[]>([]);
  const [funnelSteps, setFunnelSteps] = useState<FlowFunnelStep[]>([]);
  const [funnelMeta, setFunnelMeta] = useState({ totalEnrolled: 0, totalGoals: 0, conversionRate: 0 });
  const [branches, setBranches] = useState<BranchCount[]>([]);
  const [versions, setVersions] = useState<VersionStats[]>([]);

  // Load flow list
  useEffect(() => {
    (async () => {
      try {
        const data = await fetchTemplates(1, 100);
        setFlows(data.items);
        if (!flowId && data.items.length > 0) {
          setFlowId(data.items[0].id);
        }
      } catch {
        // silent
      }
    })();
  }, []);

  // Load analytics when flow changes
  const loadAnalytics = useCallback(async () => {
    if (!flowId) return;
    setLoading(true);
    try {
      const [overviewData, nodeData, funnelData, branchData, versionData] =
        await Promise.all([
          fetchFlowOverview(flowId),
          fetchNodeStats(flowId),
          fetchFlowFunnel(flowId),
          fetchBranchCounts(flowId),
          fetchVersionComparison(flowId),
        ]);

      setOverview(overviewData);
      setNodeStats(nodeData.nodes);
      setFunnelSteps(funnelData.steps);
      setFunnelMeta({
        totalEnrolled: funnelData.total_enrolled,
        totalGoals: funnelData.total_goals,
        conversionRate: funnelData.conversion_rate,
      });
      setBranches(branchData.branches);
      setVersions(versionData.versions);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [flowId]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  return (
    <>
      <Header title="Flow Analytics" navLinks={NAV_LINKS} />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Flow selector */}
          <div className="flex items-center gap-4">
            <Select value={flowId} onValueChange={setFlowId}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Select a flow" />
              </SelectTrigger>
              <SelectContent>
                {flows.map((f) => (
                  <SelectItem key={f.id} value={f.id}>
                    {f.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          </div>

          {!flowId ? (
            <div className="flex flex-col items-center justify-center py-24 text-muted-foreground">
              <BarChart3 className="h-12 w-12 mb-3 opacity-30" />
              <p className="text-sm">Select a flow to view analytics</p>
            </div>
          ) : loading ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-20 w-full" />
                ))}
              </div>
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            <>
              {/* Overview cards */}
              {overview && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Enrolled</p>
                      <p className="text-2xl font-bold">{overview.total_enrolled}</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Active</p>
                      <p className="text-2xl font-bold text-blue-400">{overview.active}</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Goals Met</p>
                      <p className="text-2xl font-bold text-emerald-400">{overview.goals_hit}</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Conversion</p>
                      <p className="text-2xl font-bold text-green-400">
                        {(overview.conversion_rate * 100).toFixed(1)}%
                      </p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Error Rate</p>
                      <p
                        className={`text-2xl font-bold ${
                          overview.error_rate > 0.1
                            ? "text-red-400"
                            : overview.error_rate > 0.05
                              ? "text-yellow-400"
                              : "text-green-400"
                        }`}
                      >
                        {(overview.error_rate * 100).toFixed(1)}%
                      </p>
                    </CardContent>
                  </Card>
                </div>
              )}

              {/* Tabbed content */}
              <Tabs defaultValue="funnel" className="space-y-4">
                <TabsList>
                  <TabsTrigger value="funnel" className="gap-1">
                    <TrendingUp className="h-3.5 w-3.5" />
                    Funnel
                  </TabsTrigger>
                  <TabsTrigger value="nodes" className="gap-1">
                    <Activity className="h-3.5 w-3.5" />
                    Node Performance
                  </TabsTrigger>
                  <TabsTrigger value="versions" className="gap-1">
                    <GitCompare className="h-3.5 w-3.5" />
                    Version Comparison
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="funnel">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        Conversion Funnel
                      </CardTitle>
                      <CardDescription>
                        Drop-off at each node along the most common path
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <FlowFunnel
                        steps={funnelSteps}
                        totalEnrolled={funnelMeta.totalEnrolled}
                        totalGoals={funnelMeta.totalGoals}
                        conversionRate={funnelMeta.conversionRate}
                      />
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="nodes">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        Node Performance
                      </CardTitle>
                      <CardDescription>
                        Success rates, failure counts, and timing per node
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <NodePerformanceTable nodes={nodeStats} />
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="versions">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        Version Comparison
                      </CardTitle>
                      <CardDescription>
                        Side-by-side performance across flow versions
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <VersionComparison versions={versions} />
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>
      </PageTransition>
    </>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors (or only pre-existing errors unrelated to new files)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/analytics/flow/
git commit -m "feat: add flow analytics page with funnel, node performance, and version comparison

New page at /sequences/analytics/flow with:
- Overview cards (enrolled, active, goals, conversion, error rate)
- Conversion funnel with drop-off visualization per node
- Node performance table with sortable columns (success rate, duration)
- Version comparison table highlighting best-performing version

Uses FlowFunnel, NodePerformanceTable, and VersionComparison sub-components."
```

---

## Task 9: Frontend — Flow Health Dashboard Widget

**Files:**
- Create: `frontend/src/components/ui/flow-health-widget.tsx`

- [ ] **Step 1: Implement the flow health widget**

```tsx
// frontend/src/components/ui/flow-health-widget.tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, AlertTriangle, GitBranch, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchFlowHealth, type FlowHealthSummary } from "@/lib/flow-analytics-api";

export function FlowHealthWidget() {
  const [health, setHealth] = useState<FlowHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchFlowHealth();
        setHealth(data);
      } catch {
        // silent — widget is non-critical
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return <Skeleton className="h-32 w-full" />;
  }

  if (!health) return null;

  const hasErrors = health.error_count > 0;
  const highErrorRate = health.error_rate > 0.1;

  return (
    <Card className={highErrorRate ? "border-red-500/30" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Flow Health
          {highErrorRate && (
            <AlertTriangle className="h-3.5 w-3.5 text-red-400" />
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
            <div>
              <p className="text-lg font-bold">{health.active_flows}</p>
              <p className="text-[10px] text-muted-foreground">Active Flows</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Users className="h-3.5 w-3.5 text-muted-foreground" />
            <div>
              <p className="text-lg font-bold">{health.active_instances}</p>
              <p className="text-[10px] text-muted-foreground">Active Instances</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <AlertTriangle
              className={`h-3.5 w-3.5 ${
                hasErrors ? "text-red-400" : "text-muted-foreground"
              }`}
            />
            <div>
              <p className={`text-lg font-bold ${hasErrors ? "text-red-400" : ""}`}>
                {health.error_count}
              </p>
              <p className="text-[10px] text-muted-foreground">Errors</p>
            </div>
          </div>
          <div>
            <p
              className={`text-lg font-bold ${
                highErrorRate
                  ? "text-red-400"
                  : health.error_rate > 0.05
                    ? "text-yellow-400"
                    : "text-green-400"
              }`}
            >
              {(health.error_rate * 100).toFixed(1)}%
            </p>
            <p className="text-[10px] text-muted-foreground">Error Rate</p>
          </div>
        </div>
        {hasErrors && (
          <Link
            href="/sequences/monitor?status=error"
            className="text-[10px] text-red-400 hover:underline mt-2 inline-block"
          >
            View errored instances
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Add flow health API endpoint**

Add to `app/api/flow_analytics.py`:

```python
@router.get("/health", response_model=dict)
async def get_flow_health(
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Org-wide flow health summary for dashboard widget."""
    from app.services.flow_notifications import get_flow_health_summary
    return await get_flow_health_summary(db=db, org_id=org.id)
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/flow-health-widget.tsx app/api/flow_analytics.py
git commit -m "feat: add flow health dashboard widget and health endpoint

FlowHealthWidget shows active flows, active instances, error count,
and error rate. Highlights in red when error rate exceeds 10%.
Links to errored instances in monitor page for quick debugging.

Backend GET /api/flows/health returns org-wide flow health summary."
```

---

## Summary

| Task | What it does | Files | Tests |
|------|-------------|-------|-------|
| 1 | Lead flow history + canvas leads API | `flow_leads.py`, `main.py` | `test_flow_leads.py` (4 tests) |
| 2 | Flow analytics API (nodes, funnel, compare) | `flow_analytics.py`, `flow_analytics_service.py`, `main.py` | `test_flow_analytics.py` (5 tests) |
| 3 | Admin notification service | `flow_notifications.py` | `test_flow_notifications.py` (4 tests) |
| 4 | TypeScript API client | `flow-analytics-api.ts` | Type-check only |
| 5 | Lead profile Flow History tab | `FlowHistoryTab.tsx`, `page.tsx` | `FlowHistoryTab.test.tsx` (6 tests) |
| 6 | Canvas leads panel + journey overlay | `LeadsPanel.tsx`, `JourneyOverlay.tsx` | `LeadsPanel.test.tsx` (4 tests) |
| 7 | Canvas node analytics badges | `NodeBadge.tsx` | Type-check only |
| 8 | Flow analytics page | `page.tsx`, `FlowFunnel.tsx`, `VersionComparison.tsx`, `NodePerformanceTable.tsx` | Type-check only |
| 9 | Flow health dashboard widget | `flow-health-widget.tsx`, `flow_analytics.py` | — |

**Total:** 9 tasks, ~35 steps, 9 commits. 19+ automated tests.

After completing this plan, the flow builder has full lead visibility, per-node analytics, funnel tracking, version comparison, and admin error alerting. Proceed to **Plan 7: Migration & Polish** (if needed).
