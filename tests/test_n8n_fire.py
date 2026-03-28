"""Tests for fire_n8n_automations orchestrator in app/services/n8n_webhook.py."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

import pytest

from app.services.n8n_webhook import fire_n8n_automations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot(automations):
    """Create a SimpleNamespace bot_config with n8n_automations + common attrs."""
    return SimpleNamespace(
        n8n_automations=automations,
        agent_name="TestBot",
        company_name="Acme",
        context_variables=None,
        goal_config=None,
        language="en",
    )


def _auto(timing="post_call", enabled=True, url="https://hook.example.com/1", **kw):
    """Shortcut to build an automation dict."""
    return {
        "id": kw.pop("id", "auto-1"),
        "name": kw.pop("name", "Test Auto"),
        "timing": timing,
        "enabled": enabled,
        "webhook_url": url,
        "payload_sections": kw.pop("payload_sections", ["call"]),
        **kw,
    }


CALL_DATA = {"call_sid": "sid-1", "outcome": "completed"}
ANALYSIS = {"sentiment": "positive", "summary": "good call"}

PATCH_SEND = "app.services.n8n_webhook._send_webhook"


# ---------------------------------------------------------------------------
# TestAutomationFiltering
# ---------------------------------------------------------------------------


class TestAutomationFiltering:
    """Verify that fire_n8n_automations selects the right automations."""

    @pytest.mark.asyncio
    async def test_filters_by_timing(self):
        bot = _bot([_auto(timing="pre_call"), _auto(timing="post_call", id="auto-2")])
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("pre_call", bot, CALL_DATA)
        assert mock.await_count == 1
        # The webhook_url of the pre_call auto was called
        mock.assert_awaited_once()
        assert mock.call_args[0][0] == "https://hook.example.com/1"

    @pytest.mark.asyncio
    async def test_skips_disabled(self):
        bot = _bot([_auto(enabled=False)])
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_automations_list(self):
        bot = _bot([])
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_automations_attribute(self):
        bot = _bot(None)
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_automations_attribute(self):
        bot = SimpleNamespace(agent_name="X", company_name="Y", context_variables=None, goal_config=None, language="en")
        # no n8n_automations attr at all
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_only_matching_timing_fires(self):
        autos = [
            _auto(timing="pre_call", id="a1", url="https://hook.example.com/pre"),
            _auto(timing="post_call", id="a2", url="https://hook.example.com/post1"),
            _auto(timing="post_call", id="a3", url="https://hook.example.com/post2"),
        ]
        bot = _bot(autos)
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        assert mock.await_count == 2
        urls_called = {call.args[0] for call in mock.call_args_list}
        assert urls_called == {"https://hook.example.com/post1", "https://hook.example.com/post2"}


# ---------------------------------------------------------------------------
# TestConditionEvaluationIntegration
# ---------------------------------------------------------------------------


class TestConditionEvaluationIntegration:
    """Conditions are evaluated for post_call automations."""

    @pytest.mark.asyncio
    async def test_fires_when_conditions_met(self):
        auto = _auto(
            conditions=[{"field": "sentiment", "operator": "equals", "value": "positive"}],
            condition_logic="all",
        )
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA, analysis=ANALYSIS)
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_conditions_not_met(self):
        auto = _auto(
            conditions=[{"field": "sentiment", "operator": "equals", "value": "negative"}],
            condition_logic="all",
        )
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA, analysis=ANALYSIS)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fires_with_no_conditions(self):
        auto = _auto(conditions=[])
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestConcurrentFiring
# ---------------------------------------------------------------------------


class TestConcurrentFiring:
    """Webhooks fire concurrently via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_multiple_webhooks_concurrent(self):
        autos = [
            _auto(id="a1", url="https://hook.example.com/1"),
            _auto(id="a2", url="https://hook.example.com/2"),
            _auto(id="a3", url="https://hook.example.com/3"),
        ]
        bot = _bot(autos)
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        assert mock.await_count == 3

    @pytest.mark.asyncio
    async def test_one_fails_others_succeed(self):
        autos = [
            _auto(id="a1", url="https://hook.example.com/1"),
            _auto(id="a2", url="https://hook.example.com/2"),
        ]
        bot = _bot(autos)
        with patch(PATCH_SEND, new_callable=AsyncMock, side_effect=[True, False]) as mock:
            # Should not raise
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_all_fail_no_raise(self):
        autos = [
            _auto(id="a1", url="https://hook.example.com/1"),
            _auto(id="a2", url="https://hook.example.com/2"),
        ]
        bot = _bot(autos)
        with patch(PATCH_SEND, new_callable=AsyncMock, side_effect=Exception("boom")):
            # gather with return_exceptions=True — should not propagate
            await fire_n8n_automations("post_call", bot, CALL_DATA)

    @pytest.mark.asyncio
    async def test_partial_match_fires_subset(self):
        autos = [
            _auto(timing="pre_call", id="a1"),
            _auto(timing="post_call", id="a2"),
            _auto(timing="post_call", id="a3", enabled=False),
        ]
        bot = _bot(autos)
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        assert mock.await_count == 1


# ---------------------------------------------------------------------------
# TestPayloadConstruction
# ---------------------------------------------------------------------------


class TestPayloadConstruction:
    """Verify build_payload is called with correct args for each automation."""

    @pytest.mark.asyncio
    async def test_correct_args_to_build_payload(self):
        auto = _auto(payload_sections=["call", "analysis"])
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as send_mock, \
             patch("app.services.n8n_webhook.build_payload", wraps=__import__("app.services.n8n_webhook", fromlist=["build_payload"]).build_payload) as bp_mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA, analysis=ANALYSIS, contact={"contact_name": "Jo"}, transcript=[{"role": "bot", "text": "Hi"}])
        bp_mock.assert_called_once()
        kw = bp_mock.call_args
        assert kw.kwargs["call_data"] == CALL_DATA
        assert kw.kwargs["analysis"] == ANALYSIS
        assert kw.kwargs["contact"] == {"contact_name": "Jo"}
        assert kw.kwargs["transcript"] == [{"role": "bot", "text": "Hi"}]

    @pytest.mark.asyncio
    async def test_each_automation_gets_own_payload(self):
        autos = [
            _auto(id="a1", url="https://hook.example.com/1", name="First"),
            _auto(id="a2", url="https://hook.example.com/2", name="Second"),
        ]
        bot = _bot(autos)
        payloads_sent = []

        async def capture_send(url, payload, auto_id, **kw):
            payloads_sent.append((url, payload.get("automation_id")))
            return True

        with patch(PATCH_SEND, side_effect=capture_send):
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        assert len(payloads_sent) == 2
        ids = {p[1] for p in payloads_sent}
        assert ids == {"a1", "a2"}


# ---------------------------------------------------------------------------
# TestMalformedConfig
# ---------------------------------------------------------------------------


class TestMalformedConfig:
    """Gracefully handle broken automation configs."""

    @pytest.mark.asyncio
    async def test_missing_webhook_url(self):
        auto = _auto()
        auto.pop("webhook_url")
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_timing(self):
        auto = _auto()
        auto.pop("timing")
        bot = _bot([auto])
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_dict_entry_skipped(self):
        bot = _bot(["not-a-dict", 42, None, _auto()])
        with patch(PATCH_SEND, new_callable=AsyncMock, return_value=True) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        # Only the valid dict auto should fire
        assert mock.await_count == 1

    @pytest.mark.asyncio
    async def test_string_not_list_automations(self):
        bot = _bot("not-a-list")
        with patch(PATCH_SEND, new_callable=AsyncMock) as mock:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
        mock.assert_not_awaited()
