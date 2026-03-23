"""Tests for Plivo status mapping and call outcome feedback loop.

Imports from app.plivo.status_mapping (no pipecat dependency).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.plivo.status_mapping import _map_plivo_status, _update_sequence_touchpoint


# --- Task 1: Plivo Status Granularity ---


def test_map_plivo_status_preserves_busy():
    assert _map_plivo_status("busy") == "busy"


def test_map_plivo_status_preserves_timeout():
    assert _map_plivo_status("timeout") == "timeout"


def test_map_plivo_status_preserves_no_answer():
    assert _map_plivo_status("no-answer") == "no_answer"


def test_map_plivo_status_completed_maps_to_picked_up():
    assert _map_plivo_status("completed") == "picked_up"


def test_map_plivo_status_machine_maps_to_voicemail():
    assert _map_plivo_status("machine") == "voicemail"


def test_map_plivo_status_cancel_maps_to_failed():
    assert _map_plivo_status("cancel") == "failed"


def test_map_plivo_status_failed_stays_failed():
    assert _map_plivo_status("failed") == "failed"


def test_map_plivo_status_unknown_returns_unknown():
    assert _map_plivo_status("some_new_status") == "unknown"


def test_map_plivo_status_none_returns_unknown():
    assert _map_plivo_status(None) == "unknown"


# --- Task 2: Call Outcome Feedback Loop ---


@pytest.mark.asyncio
async def test_update_touchpoint_on_call_outcome():
    """When plivo_event fires, it should update the sequence touchpoint status."""
    mock_db = AsyncMock()
    mock_touchpoint = MagicMock(
        id="tp-123",
        status="scheduled",
        step_snapshot={},
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_touchpoint
    mock_db.execute = AsyncMock(return_value=mock_result)

    await _update_sequence_touchpoint(
        db=mock_db,
        touchpoint_id="tp-123",
        call_outcome="picked_up",
        raw_plivo_status="completed",
    )

    assert mock_touchpoint.status == "sent"
    assert mock_touchpoint.step_snapshot["call_outcome"] == "picked_up"
    assert mock_touchpoint.step_snapshot["raw_plivo_status"] == "completed"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_touchpoint_skips_if_not_found():
    """Should not error if touchpoint ID doesn't exist."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    await _update_sequence_touchpoint(
        db=mock_db,
        touchpoint_id="nonexistent",
        call_outcome="picked_up",
        raw_plivo_status="completed",
    )

    mock_db.commit.assert_not_called()
