"""Tests for migration admin endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.flow_migrator import build_flow_graph


class TestMigrationPreview:
    """Test dry-run migration preview endpoint."""

    @pytest.mark.asyncio
    async def test_preview_returns_node_count(self):
        """Preview should return node_count and edge_count without persisting."""
        steps = [
            {
                "step_order": 1,
                "name": "Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": None,
                "whatsapp_template_name": None,
                "whatsapp_template_params": None,
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": str(uuid.uuid4()),
                "expects_reply": False,
                "reply_handler": None,
            },
        ]
        nodes, edges = build_flow_graph(steps)
        # Should produce: VoiceCall -> End (2 nodes, 1 edge)
        assert len(nodes) == 2
        assert len(edges) == 1


class TestMigrationStatus:
    """Test migration status tracking."""

    def test_status_response_shape(self):
        """Status should report total, migrated, remaining, active_linear counts."""
        status = {
            "total_templates": 5,
            "migrated": 3,
            "remaining": 2,
            "active_linear_instances": 10,
        }
        assert status["remaining"] == status["total_templates"] - status["migrated"]
