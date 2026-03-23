import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

@pytest.mark.asyncio
async def test_simulate_flow_returns_path():
    """POST /api/flows/{id}/versions/{vid}/simulate returns simulated path."""
    from app.api.flow_simulation import simulate_flow

    mock_db = AsyncMock()

    # Mock version with nodes + edges
    mock_version = MagicMock()
    mock_version.id = "v1"
    mock_version.flow_id = "f1"

    mock_nodes = [
        MagicMock(id="n1", node_type="voice_call", name="Call", config={"bot_id": "b1"}, position_x=0, position_y=0),
        MagicMock(id="n2", node_type="condition", name="Check", config={
            "conditions": [{"label": "hot", "rules": [{"field": "interest_level", "operator": "gte", "value": 7}]}],
            "default_label": "cold",
        }, position_x=0, position_y=200),
        MagicMock(id="n3", node_type="end", name="End", config={}, position_x=0, position_y=400),
    ]
    mock_edges = [
        MagicMock(id="e1", source_node_id="n1", target_node_id="n2", condition_label="default"),
        MagicMock(id="e2", source_node_id="n2", target_node_id="n3", condition_label="hot"),
        MagicMock(id="e3", source_node_id="n2", target_node_id="n3", condition_label="cold"),
    ]

    with patch("app.api.flow_simulation._get_version_graph") as mock_get:
        mock_get.return_value = (mock_nodes, mock_edges, "n1")

        result = await simulate_flow(
            db=mock_db,
            flow_id="f1",
            version_id="v1",
            org_id="org-1",
            mock_lead={"name": "Test", "phone": "+91999", "interest_level": 9},
            outcomes={},  # Let auto-evaluate handle conditions
        )

    assert len(result["path"]) == 3
    assert result["path"][0]["node_id"] == "n1"
    assert result["path"][1]["node_id"] == "n2"
    assert result["path"][2]["node_id"] == "n3"
    assert result["end_reason"] == "reached_end"


@pytest.mark.asyncio
async def test_simulate_with_manual_outcomes():
    """Manual outcomes override auto-evaluation at condition nodes."""
    from app.api.flow_simulation import simulate_flow

    mock_db = AsyncMock()

    mock_nodes = [
        MagicMock(id="n1", node_type="voice_call", name="Call", config={}, position_x=0, position_y=0),
        MagicMock(id="n2", node_type="condition", name="Check", config={
            "conditions": [{"label": "hot", "rules": [{"field": "interest_level", "operator": "gte", "value": 7}]}],
            "default_label": "cold",
        }, position_x=0, position_y=200),
        MagicMock(id="n3", node_type="whatsapp_template", name="Follow Up", config={}, position_x=-100, position_y=400),
        MagicMock(id="n4", node_type="end", name="End", config={}, position_x=100, position_y=400),
    ]
    mock_edges = [
        MagicMock(id="e1", source_node_id="n1", target_node_id="n2", condition_label="default"),
        MagicMock(id="e2", source_node_id="n2", target_node_id="n3", condition_label="hot"),
        MagicMock(id="e3", source_node_id="n2", target_node_id="n4", condition_label="cold"),
    ]

    with patch("app.api.flow_simulation._get_version_graph") as mock_get:
        mock_get.return_value = (mock_nodes, mock_edges, "n1")

        # Force "cold" even though interest_level=9 would auto-eval to "hot"
        result = await simulate_flow(
            db=mock_db,
            flow_id="f1",
            version_id="v1",
            org_id="org-1",
            mock_lead={"name": "Test", "phone": "+91999", "interest_level": 9},
            outcomes={"n2": "cold"},
        )

    assert result["path"][2]["node_id"] == "n4"  # Went to End, not Follow Up


@pytest.mark.asyncio
async def test_create_live_test_instance():
    """POST /api/flows/{id}/live-test creates instance with is_test=true."""
    from app.api.flow_simulation import create_live_test

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    # Mock the published version lookup
    mock_version = MagicMock()
    mock_version.id = "v1"
    mock_version.flow_id = "f1"

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_version
    mock_db.execute.return_value = mock_result

    with patch("app.api.flow_simulation._find_or_create_test_lead") as mock_lead, \
         patch("app.api.flow_simulation._get_entry_node_id") as mock_entry:
        mock_lead.return_value = "lead-test-1"
        mock_entry.return_value = "n1"

        result = await create_live_test(
            db=mock_db,
            flow_id="f1",
            org_id="org-1",
            phone_number="+919876543210",
            delay_ratio=60,  # 1 hour → 1 minute
        )

    assert result["is_test"] is True
    assert result["delay_ratio"] == 60
    mock_db.commit.assert_called()


@pytest.mark.asyncio
async def test_live_test_validates_phone():
    """Live test rejects invalid phone numbers."""
    from app.api.flow_simulation import create_live_test

    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="valid phone"):
        await create_live_test(
            db=mock_db,
            flow_id="f1",
            org_id="org-1",
            phone_number="invalid",
            delay_ratio=60,
        )
