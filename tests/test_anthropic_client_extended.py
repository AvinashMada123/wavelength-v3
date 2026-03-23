"""Extended tests for anthropic_client — interpolation edge cases,
variable extraction, MODEL_MAP, and cost constants."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.services.anthropic_client import (
    _interpolate_variables,
    extract_variable_names,
    MODEL_MAP,
    COST_PER_1M_INPUT,
    COST_PER_1M_OUTPUT,
)


# ---------------------------------------------------------------------------
# _interpolate_variables — extended edge cases
# ---------------------------------------------------------------------------

class TestInterpolateVariablesExtended:
    def test_basic_replacement(self):
        result = _interpolate_variables("Hello {{name}}", {"name": "Alice"})
        assert result == "Hello Alice"

    def test_multiple_same_variable(self):
        result = _interpolate_variables("{{x}} and {{x}}", {"x": "A"})
        assert result == "A and A"

    def test_multiple_different_variables(self):
        result = _interpolate_variables(
            "{{a}} {{b}} {{c}}",
            {"a": "1", "b": "2", "c": "3"},
        )
        assert result == "1 2 3"

    def test_missing_variable_left_as_is(self):
        result = _interpolate_variables("{{exists}} {{missing}}", {"exists": "yes"})
        assert result == "yes {{missing}}"

    def test_empty_variables_dict(self):
        result = _interpolate_variables("{{name}}", {})
        assert result == "{{name}}"

    def test_no_placeholders(self):
        result = _interpolate_variables("No variables here", {"name": "Alice"})
        assert result == "No variables here"

    def test_empty_prompt(self):
        result = _interpolate_variables("", {"name": "Alice"})
        assert result == ""

    def test_variable_with_spaces_in_braces(self):
        """Spaces inside {{ }} should be stripped."""
        result = _interpolate_variables("{{ name }}", {"name": "Alice"})
        assert result == "Alice"

    def test_numeric_value(self):
        result = _interpolate_variables("Count: {{n}}", {"n": 42})
        assert result == "Count: 42"

    def test_none_value(self):
        result = _interpolate_variables("Val: {{x}}", {"x": None})
        assert result == "Val: None"

    def test_nested_braces_not_matched(self):
        """Triple braces should only match the inner pair."""
        result = _interpolate_variables("{{{name}}}", {"name": "A"})
        assert result == "{A}"

    def test_single_braces_not_matched(self):
        result = _interpolate_variables("{name}", {"name": "A"})
        assert result == "{name}"

    def test_multiline_prompt(self):
        prompt = "Line 1: {{a}}\nLine 2: {{b}}"
        result = _interpolate_variables(prompt, {"a": "X", "b": "Y"})
        assert result == "Line 1: X\nLine 2: Y"

    def test_special_characters_in_value(self):
        result = _interpolate_variables("{{msg}}", {"msg": "Hello & welcome <to> 'this'"})
        assert result == "Hello & welcome <to> 'this'"

    def test_empty_string_value(self):
        result = _interpolate_variables("Hello {{name}}!", {"name": ""})
        assert result == "Hello !"

    def test_boolean_value(self):
        result = _interpolate_variables("Active: {{active}}", {"active": True})
        assert result == "Active: True"


# ---------------------------------------------------------------------------
# extract_variable_names — extended edge cases
# ---------------------------------------------------------------------------

class TestExtractVariableNamesExtended:
    def test_basic(self):
        assert extract_variable_names("{{a}} {{b}}") == {"a", "b"}

    def test_duplicates_returned_once(self):
        assert extract_variable_names("{{x}} {{x}} {{x}}") == {"x"}

    def test_no_variables(self):
        assert extract_variable_names("no variables") == set()

    def test_empty_string(self):
        assert extract_variable_names("") == set()

    def test_spaces_in_braces_stripped(self):
        names = extract_variable_names("{{ name }} {{ city }}")
        assert names == {"name", "city"}

    def test_single_braces_not_matched(self):
        assert extract_variable_names("{name}") == set()

    def test_underscored_names(self):
        assert extract_variable_names("{{first_name}} {{last_name}}") == {"first_name", "last_name"}

    def test_mixed_text_and_vars(self):
        prompt = "Dear {{name}}, your order #{{order_id}} is at {{location}}."
        assert extract_variable_names(prompt) == {"name", "order_id", "location"}

    def test_multiline(self):
        prompt = "Line 1: {{a}}\nLine 2: {{b}}\nLine 3: {{c}}"
        assert extract_variable_names(prompt) == {"a", "b", "c"}

    def test_adjacent_vars(self):
        assert extract_variable_names("{{a}}{{b}}") == {"a", "b"}


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestAnthropicConstants:
    def test_model_map_has_sonnet(self):
        assert "claude-sonnet" in MODEL_MAP
        assert "claude-sonnet" in MODEL_MAP["claude-sonnet"]  # contains "sonnet"

    def test_model_map_has_haiku(self):
        assert "claude-haiku" in MODEL_MAP
        assert "haiku" in MODEL_MAP["claude-haiku"]

    def test_cost_maps_aligned(self):
        """Input and output cost maps should have the same keys."""
        assert set(COST_PER_1M_INPUT.keys()) == set(COST_PER_1M_OUTPUT.keys())

    def test_haiku_cheaper_than_sonnet(self):
        assert COST_PER_1M_INPUT["claude-haiku"] < COST_PER_1M_INPUT["claude-sonnet"]
        assert COST_PER_1M_OUTPUT["claude-haiku"] < COST_PER_1M_OUTPUT["claude-sonnet"]


# ---------------------------------------------------------------------------
# generate_content — async tests with mocked Anthropic client
# ---------------------------------------------------------------------------

class TestGenerateContent:
    @pytest.mark.asyncio
    async def test_successful_generation_returns_stripped_text(self):
        mock_response = SimpleNamespace(
            content=[SimpleNamespace(text="  Hello, world!  ")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_client.close = AsyncMock()

        with patch("app.services.anthropic_client.anthropic") as mock_anthropic, \
             patch("app.services.anthropic_client.settings", SimpleNamespace(ANTHROPIC_API_KEY="fake")):
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.services.anthropic_client import generate_content
            result = await generate_content("Hello {{name}}", {"name": "Alice"})
            assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_api_error_re_raises(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        mock_client.close = AsyncMock()

        with patch("app.services.anthropic_client.anthropic") as mock_anthropic, \
             patch("app.services.anthropic_client.settings", SimpleNamespace(ANTHROPIC_API_KEY="fake")):
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            from app.services.anthropic_client import generate_content
            with pytest.raises(RuntimeError, match="API down"):
                await generate_content("test", {})

    def test_model_mapping_claude_sonnet(self):
        assert MODEL_MAP["claude-sonnet"] == "claude-sonnet-4-20250514"
