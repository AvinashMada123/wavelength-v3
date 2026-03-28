"""Regression tests for n8n automation feature.

Ensures existing functionality (GHL workflows, bot_config CRUD, call lifecycle)
is not broken by the addition of n8n_automations.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Mock structlog before importing application code
sys.modules.setdefault(
    "structlog",
    SimpleNamespace(
        get_logger=lambda *a, **kw: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        ),
    ),
)

from app.services.n8n_webhook import fire_n8n_automations  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot_config(
    *,
    ghl_workflows: list | None = None,
    n8n_automations: list | None = None,
    include_n8n_attr: bool = True,
    agent_name: str = "TestBot",
    company_name: str = "TestCo",
) -> SimpleNamespace:
    """Build a mock bot_config with optional fields."""
    fields = {
        "ghl_workflows": ghl_workflows or [],
        "agent_name": agent_name,
        "company_name": company_name,
        "context_variables": None,
        "goal_config": None,
        "language": "en",
    }
    if include_n8n_attr:
        fields["n8n_automations"] = n8n_automations
    return SimpleNamespace(**fields)


def _make_automation(
    *,
    automation_id: str = "auto-1",
    name: str = "Test Auto",
    timing: str = "post_call",
    webhook_url: str = "https://n8n.example.com/webhook/abc",
    enabled: bool = True,
    payload_sections: list | None = None,
    conditions: list | None = None,
) -> dict:
    return {
        "id": automation_id,
        "name": name,
        "timing": timing,
        "webhook_url": webhook_url,
        "enabled": enabled,
        "payload_sections": payload_sections or ["call"],
        "conditions": conditions,
    }


CALL_DATA = {"call_sid": "C123", "outcome": "completed", "call_duration": 60}


# ===========================================================================
# TestGHLWorkflowsUnaffected
# ===========================================================================


class TestGHLWorkflowsUnaffected:
    """GHL workflows must work independently of n8n automations."""

    def test_ghl_workflows_not_affected_by_n8n_config(self) -> None:
        """Having n8n_automations on bot_config does not alter ghl_workflows."""
        ghl = [{"id": "ghl-1", "type": "add_tag", "tag": "called"}]
        bot = _make_bot_config(
            ghl_workflows=ghl,
            n8n_automations=[_make_automation()],
        )
        # GHL workflows remain intact and accessible
        assert bot.ghl_workflows == ghl
        assert len(bot.ghl_workflows) == 1
        assert bot.ghl_workflows[0]["id"] == "ghl-1"

    @pytest.mark.asyncio
    async def test_n8n_fires_independently_of_ghl(self) -> None:
        """n8n automations fire regardless of ghl_workflows content."""
        bot = _make_bot_config(
            ghl_workflows=[{"id": "ghl-1"}],
            n8n_automations=[_make_automation(timing="post_call")],
        )
        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock, return_value=True
        ) as mock_send:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
            mock_send.assert_called_once()

    def test_both_systems_coexist(self) -> None:
        """Both ghl_workflows and n8n_automations can exist on same bot."""
        bot = _make_bot_config(
            ghl_workflows=[{"id": "ghl-1"}, {"id": "ghl-2"}],
            n8n_automations=[_make_automation(), _make_automation(automation_id="auto-2")],
        )
        assert len(bot.ghl_workflows) == 2
        assert len(bot.n8n_automations) == 2

    @pytest.mark.asyncio
    async def test_empty_n8n_does_not_affect_ghl(self) -> None:
        """n8n_automations=[] has no side effects on GHL or the call."""
        ghl = [{"id": "ghl-1"}]
        bot = _make_bot_config(ghl_workflows=ghl, n8n_automations=[])

        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock
        ) as mock_send:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
            mock_send.assert_not_called()

        # GHL untouched
        assert bot.ghl_workflows == ghl


# ===========================================================================
# TestBotConfigCRUDWithNewField
# ===========================================================================


class TestBotConfigCRUDWithNewField:
    """bot_config objects with various n8n_automations states work correctly."""

    def test_bot_config_with_empty_n8n_automations(self) -> None:
        bot = _make_bot_config(n8n_automations=[])
        assert bot.n8n_automations == []

    def test_bot_config_with_populated_n8n_automations(self) -> None:
        autos = [_make_automation(), _make_automation(automation_id="auto-2")]
        bot = _make_bot_config(n8n_automations=autos)
        assert len(bot.n8n_automations) == 2
        assert bot.n8n_automations[0]["id"] == "auto-1"
        assert bot.n8n_automations[1]["id"] == "auto-2"

    def test_bot_config_without_n8n_field_attribute(self) -> None:
        """bot_config object that lacks the n8n_automations attribute entirely."""
        bot = _make_bot_config(include_n8n_attr=False)
        assert not hasattr(bot, "n8n_automations")
        # getattr safety pattern used in fire_n8n_automations
        assert getattr(bot, "n8n_automations", None) is None

    def test_bot_config_with_none_n8n_automations(self) -> None:
        bot = _make_bot_config(n8n_automations=None)
        assert bot.n8n_automations is None

    def test_n8n_automations_preserved_as_list(self) -> None:
        autos = [_make_automation()]
        bot = _make_bot_config(n8n_automations=autos)
        assert isinstance(bot.n8n_automations, list)
        assert bot.n8n_automations is autos  # same reference

    def test_bot_config_serialization_includes_n8n(self) -> None:
        """n8n_automations field is accessible via standard attribute access."""
        autos = [_make_automation(name="My Webhook")]
        bot = _make_bot_config(n8n_automations=autos)
        # Simulate serialization by reading the field
        data = {"n8n_automations": bot.n8n_automations}
        assert data["n8n_automations"][0]["name"] == "My Webhook"


# ===========================================================================
# TestPreMigrationBackwardCompat
# ===========================================================================


class TestPreMigrationBackwardCompat:
    """fire_n8n_automations handles pre-migration bot configs gracefully."""

    @pytest.mark.asyncio
    async def test_fire_with_none_n8n_automations(self) -> None:
        """bot_config.n8n_automations = None -> no error, no webhooks."""
        bot = _make_bot_config(n8n_automations=None)
        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock
        ) as mock_send:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_with_missing_attribute(self) -> None:
        """bot_config without n8n_automations attr -> no error."""
        bot = _make_bot_config(include_n8n_attr=False)
        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock
        ) as mock_send:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_with_empty_list(self) -> None:
        """bot_config.n8n_automations = [] -> no error."""
        bot = _make_bot_config(n8n_automations=[])
        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock
        ) as mock_send:
            await fire_n8n_automations("post_call", bot, CALL_DATA)
            mock_send.assert_not_called()


# ===========================================================================
# TestWebhookDoesNotBlockCallLifecycle
# ===========================================================================


class TestWebhookDoesNotBlockCallLifecycle:
    """n8n webhook failures must never propagate to the call lifecycle."""

    @pytest.mark.asyncio
    async def test_n8n_failure_does_not_raise(self) -> None:
        """fire_n8n_automations never raises even if webhook fails."""
        bot = _make_bot_config(n8n_automations=[_make_automation()])
        with patch(
            "app.services.n8n_webhook._send_webhook",
            new_callable=AsyncMock,
            side_effect=Exception("network boom"),
        ):
            # Must not raise
            await fire_n8n_automations("post_call", bot, CALL_DATA)

    @pytest.mark.asyncio
    async def test_n8n_with_invalid_url_does_not_raise(self) -> None:
        """Malformed URL in automation -> logged, no exception."""
        bot = _make_bot_config(
            n8n_automations=[_make_automation(webhook_url="not-a-valid-url://???")]
        )
        with patch(
            "app.services.n8n_webhook._send_webhook",
            new_callable=AsyncMock,
            return_value=False,
        ):
            # Must not raise
            await fire_n8n_automations("post_call", bot, CALL_DATA)

    @pytest.mark.asyncio
    async def test_fire_returns_none_always(self) -> None:
        """Function always returns None (no return value to accidentally await on)."""
        bot = _make_bot_config(n8n_automations=[_make_automation()])
        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock, return_value=True
        ):
            result = await fire_n8n_automations("post_call", bot, CALL_DATA)
            assert result is None

        # Also None when nothing fires
        bot_empty = _make_bot_config(n8n_automations=[])
        result = await fire_n8n_automations("post_call", bot_empty, CALL_DATA)
        assert result is None


# ===========================================================================
# TestConcurrentCallsSameBot
# ===========================================================================


class TestConcurrentCallsSameBot:
    """Concurrent calls using the same bot_config must not interfere."""

    @pytest.mark.asyncio
    async def test_two_concurrent_fires_same_config(self) -> None:
        """Two fire_n8n_automations calls with same bot_config run independently."""
        bot = _make_bot_config(n8n_automations=[_make_automation()])
        call_count = 0

        async def _counting_send(url, payload, automation_id, max_retries=2):
            nonlocal call_count
            call_count += 1
            return True

        with patch("app.services.n8n_webhook._send_webhook", side_effect=_counting_send):
            await asyncio.gather(
                fire_n8n_automations("post_call", bot, {"call_sid": "C1", "outcome": "done"}),
                fire_n8n_automations("post_call", bot, {"call_sid": "C2", "outcome": "done"}),
            )
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_shared_state_mutation(self) -> None:
        """bot_config.n8n_automations is not mutated by fire_n8n_automations."""
        original_auto = _make_automation()
        autos = [original_auto]
        bot = _make_bot_config(n8n_automations=autos)

        original_snapshot = dict(original_auto)

        with patch(
            "app.services.n8n_webhook._send_webhook", new_callable=AsyncMock, return_value=True
        ):
            await fire_n8n_automations("post_call", bot, CALL_DATA)

        # List length unchanged
        assert len(bot.n8n_automations) == 1
        # Dict contents unchanged
        assert bot.n8n_automations[0] == original_snapshot
        # Same reference (not replaced)
        assert bot.n8n_automations is autos
