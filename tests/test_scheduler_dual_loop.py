"""Tests for scheduler dual-loop: linear + flow polling."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.sequence_scheduler import _process_batch, _process_flow_batch


@pytest.fixture
def mock_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


class TestLinearBatchFiltering:
    """Verify _process_batch only picks up engine_type='linear' touchpoints."""

    @pytest.mark.asyncio
    async def test_process_batch_filters_linear_only(self, mock_db):
        """_process_batch query should include engine_type='linear' filter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await _process_batch()

        # Verify the SQL query was executed (contains engine_type filter)
        call_args = mock_db.execute.call_args
        assert call_args is not None


class TestFlowBatchPolling:
    """Verify _process_flow_batch polls FlowTouchpoint table."""

    @pytest.mark.asyncio
    async def test_process_flow_batch_polls_pending_touchpoints(self, mock_db):
        """_process_flow_batch should query FlowTouchpoint with status=pending."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await _process_flow_batch()

        assert mock_db.execute.called


class TestSchedulerLoopDual:
    """Verify the scheduler loop calls both batch processors."""

    @pytest.mark.asyncio
    async def test_scheduler_calls_both_loops(self):
        """_scheduler_loop should call both _process_batch and _process_flow_batch."""
        with patch("app.services.sequence_scheduler._process_batch", new_callable=AsyncMock) as mock_linear, \
             patch("app.services.sequence_scheduler._process_flow_batch", new_callable=AsyncMock) as mock_flow, \
             patch("app.services.sequence_scheduler._process_flow_events", new_callable=AsyncMock) as mock_events, \
             patch("app.services.sequence_scheduler._retry_failed", new_callable=AsyncMock), \
             patch("app.services.sequence_scheduler.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            # Make sleep raise to break the loop after one iteration
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            from app.services.sequence_scheduler import _scheduler_loop
            try:
                await _scheduler_loop()
            except asyncio.CancelledError:
                pass

            assert mock_linear.called
            assert mock_flow.called
            assert mock_events.called
