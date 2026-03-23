"""Tests for SequenceTemplate -> FlowDefinition auto-conversion."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.flow_migrator import (
    convert_step_to_node,
    build_flow_graph,
    convert_skip_conditions_to_condition_node,
    map_channel_to_node_type,
    map_timing_to_delay_node,
)


class TestChannelMapping:
    """Map SequenceStep.channel to FlowNode.node_type."""

    def test_voice_call_channel(self):
        assert map_channel_to_node_type("voice_call") == "voice_call"

    def test_whatsapp_template_channel(self):
        assert map_channel_to_node_type("whatsapp_template") == "whatsapp_template"

    def test_whatsapp_session_channel(self):
        assert map_channel_to_node_type("whatsapp_session") == "whatsapp_session"

    def test_ai_channel(self):
        assert map_channel_to_node_type("ai_message") == "ai_generate_send"

    def test_unknown_channel_defaults(self):
        """Unknown channels should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown channel"):
            map_channel_to_node_type("carrier_pigeon")


class TestStepToNodeConversion:
    """Convert a SequenceStep dict to FlowNode config."""

    def test_voice_call_step(self):
        step = {
            "name": "Follow-up Call",
            "channel": "voice_call",
            "voice_bot_id": str(uuid.uuid4()),
            "content_type": "voice",
            "skip_conditions": None,
            "timing_type": "delay",
            "timing_value": {"days": 1},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "voice_call"
        assert node["name"] == "Follow-up Call"
        assert node["config"]["bot_id"] == step["voice_bot_id"]

    def test_whatsapp_template_step(self):
        step = {
            "name": "Welcome Message",
            "channel": "whatsapp_template",
            "content_type": "template",
            "whatsapp_template_name": "welcome_v2",
            "whatsapp_template_params": {"1": "{{contact_name}}"},
            "skip_conditions": None,
            "timing_type": "immediate",
            "timing_value": {},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "whatsapp_template"
        assert node["config"]["template_name"] == "welcome_v2"
        assert node["config"]["params"] == {"1": "{{contact_name}}"}

    def test_ai_generate_step(self):
        step = {
            "name": "AI Follow-up",
            "channel": "whatsapp_session",
            "content_type": "ai_generated",
            "ai_prompt": "Write a follow-up message for {{contact_name}}",
            "ai_model": "claude-sonnet",
            "skip_conditions": None,
            "timing_type": "delay",
            "timing_value": {"hours": 2},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "ai_generate_send"
        assert node["config"]["prompt"] == step["ai_prompt"]
        assert node["config"]["model"] == "claude-sonnet"
        assert node["config"]["send_via"] == "whatsapp_session"


class TestSkipConditionConversion:
    """Convert skip_conditions to Condition nodes."""

    def test_equals_condition(self):
        skip = {"field": "interest_level", "equals": "low"}
        cond_node = convert_skip_conditions_to_condition_node(skip, step_name="Call Step")
        assert cond_node["node_type"] == "condition"
        assert cond_node["config"]["rules"][0]["field"] == "interest_level"
        assert cond_node["config"]["rules"][0]["operator"] == "equals"
        assert cond_node["config"]["rules"][0]["value"] == "low"

    def test_not_equals_condition(self):
        skip = {"field": "goal_outcome", "not_equals": "interested"}
        cond_node = convert_skip_conditions_to_condition_node(skip, step_name="Call Step")
        assert cond_node["node_type"] == "condition"
        assert cond_node["config"]["rules"][0]["operator"] == "not_equals"

    def test_none_skip_returns_none(self):
        assert convert_skip_conditions_to_condition_node(None, step_name="X") is None


class TestTimingToDelayNode:
    """Convert timing_type + timing_value to a Delay node."""

    def test_delay_days(self):
        delay = map_timing_to_delay_node("delay", {"days": 2})
        assert delay["node_type"] == "delay_wait"
        assert delay["config"]["delay_hours"] == 48

    def test_delay_hours(self):
        delay = map_timing_to_delay_node("delay", {"hours": 6})
        assert delay["config"]["delay_hours"] == 6

    def test_delay_minutes(self):
        delay = map_timing_to_delay_node("delay", {"minutes": 30})
        assert delay["config"]["delay_hours"] == 0.5

    def test_immediate_returns_none(self):
        """Immediate timing needs no delay node."""
        assert map_timing_to_delay_node("immediate", {}) is None

    def test_relative_to_event(self):
        delay = map_timing_to_delay_node(
            "relative_to_event",
            {"days": -1, "time": "09:00", "event_variable": "event_date"},
        )
        assert delay["node_type"] == "delay_wait"
        assert delay["config"]["relative_to"] == "event_date"
        assert delay["config"]["offset_days"] == -1
        assert delay["config"]["at_time"] == "09:00"


class TestBuildFlowGraph:
    """Build a complete FlowDefinition graph from a list of steps."""

    def test_simple_linear_chain(self):
        steps = [
            {
                "step_order": 1,
                "name": "Welcome",
                "channel": "whatsapp_template",
                "content_type": "template",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": None,
                "whatsapp_template_name": "welcome",
                "whatsapp_template_params": {},
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": None,
                "expects_reply": False,
                "reply_handler": None,
            },
            {
                "step_order": 2,
                "name": "Follow-up Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "delay",
                "timing_value": {"days": 1},
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

        # Should have: WA Template -> Delay(1d) -> Voice Call -> End
        # At minimum: 2 action nodes + 1 delay + 1 end = 4 nodes
        assert len(nodes) >= 3  # 2 action + 1 end minimum
        assert any(n["node_type"] == "end" for n in nodes)
        # Edges should form a chain
        assert len(edges) >= 2

    def test_steps_with_skip_condition_adds_condition_node(self):
        steps = [
            {
                "step_order": 1,
                "name": "Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": {"field": "interest_level", "equals": "low"},
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

        # Should have a condition node before the action
        condition_nodes = [n for n in nodes if n["node_type"] == "condition"]
        assert len(condition_nodes) == 1

    def test_empty_steps_produces_just_end(self):
        nodes, edges = build_flow_graph([])
        assert len(nodes) == 1
        assert nodes[0]["node_type"] == "end"
        assert len(edges) == 0
