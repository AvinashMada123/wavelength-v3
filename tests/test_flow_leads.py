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

    from app.api.flow_leads import get_db
    from app.auth.dependencies import get_current_org

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _mock_org()

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

    from app.api.flow_leads import get_db
    from app.auth.dependencies import get_current_org

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _mock_org()

    async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/leads/{FAKE_LEAD_ID}/history")

    assert resp.status_code == 200
    data = resp.json()
    assert data is not None
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

    from app.api.flow_leads import get_db
    from app.auth.dependencies import get_current_org

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _mock_org()

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

    from app.api.flow_leads import get_db
    from app.auth.dependencies import get_current_org

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _mock_org()

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

    from app.api.flow_leads import get_db
    from app.auth.dependencies import get_current_org

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _mock_org()

    async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/flows/{FAKE_FLOW_ID}/node-counts")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["counts"]) == 2
    assert data["counts"][str(FAKE_NODE_ID_1)] == 47
