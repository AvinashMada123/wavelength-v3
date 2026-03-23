import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_fetch_flow_instances_excludes_test_by_default():
    """GET /api/flows/{id}/instances excludes is_test=true by default."""
    from app.api.flow_simulation import fetch_flow_instances

    mock_db = AsyncMock()
    instances = [
        MagicMock(id="i1", is_test=False, status="active", lead_id="l1"),
        MagicMock(id="i2", is_test=True, status="active", lead_id="l2"),
    ]

    with patch("app.api.flow_simulation._query_instances") as mock_query:
        # Returns only non-test instances
        mock_query.return_value = ([instances[0]], 1)

        result = await fetch_flow_instances(
            db=mock_db, flow_id="f1", org_id="org-1", is_test=False,
        )

    assert result["total"] == 1
    assert result["instances"][0]["id"] == "i1"


@pytest.mark.asyncio
async def test_fetch_flow_instances_includes_test_when_requested():
    """GET /api/flows/{id}/instances?is_test=true shows test instances."""
    from app.api.flow_simulation import fetch_flow_instances

    mock_db = AsyncMock()
    test_instance = MagicMock(
        id="i2", is_test=True, status="active", lead_id="l2",
        lead_name="Test Lead", lead_phone="+919876543210",
        flow_id="f1", current_node_id="n1",
        started_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
        completed_at=None, error_message=None,
    )

    with patch("app.api.flow_simulation._query_instances") as mock_query:
        mock_query.return_value = ([test_instance], 1)

        result = await fetch_flow_instances(
            db=mock_db, flow_id="f1", org_id="org-1", is_test=True,
        )

    assert result["total"] == 1
    assert result["instances"][0]["is_test"] is True


@pytest.mark.asyncio
async def test_fetch_journey_data():
    """GET /api/flows/{id}/instances/{iid}/journey returns touchpoints + transitions."""
    from app.api.flow_simulation import fetch_journey_data

    mock_db = AsyncMock()

    mock_instance = MagicMock(
        id="i1", flow_id="f1", org_id="org-1",
        status="completed", is_test=False,
    )
    mock_touchpoints = [
        MagicMock(
            id="tp1", node_id="n1", status="completed",
            outcome="picked_up", scheduled_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            executed_at=datetime(2026, 3, 20, 10, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc),
            generated_content=None, error_message=None,
        ),
    ]
    mock_transitions = [
        MagicMock(
            id="tr1", from_node_id=None, to_node_id="n1",
            edge_id=None, outcome_data={},
            transitioned_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        ),
    ]

    with patch("app.api.flow_simulation._get_instance") as mock_get, \
         patch("app.api.flow_simulation._get_touchpoints") as mock_tp, \
         patch("app.api.flow_simulation._get_transitions") as mock_tr:
        mock_get.return_value = mock_instance
        mock_tp.return_value = mock_touchpoints
        mock_tr.return_value = mock_transitions

        result = await fetch_journey_data(
            db=mock_db, flow_id="f1", instance_id="i1", org_id="org-1",
        )

    assert len(result["touchpoints"]) == 1
    assert result["touchpoints"][0]["node_id"] == "n1"
    assert len(result["transitions"]) == 1


@pytest.mark.asyncio
async def test_delay_compression_applied_to_scheduler():
    """Test instances have their delays divided by delay_ratio in context_data."""
    from app.api.flow_simulation import compute_compressed_delay

    # 1 hour delay with 60x compression = 1 minute
    result = compute_compressed_delay(delay_seconds=3600, delay_ratio=60)
    assert result == 60

    # 1 day delay with 60x compression = 24 minutes
    result = compute_compressed_delay(delay_seconds=86400, delay_ratio=60)
    assert result == 1440

    # Minimum 10 seconds even with extreme compression
    result = compute_compressed_delay(delay_seconds=60, delay_ratio=1440)
    assert result >= 10
