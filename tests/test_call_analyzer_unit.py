"""Unit tests for CallAnalyzer — pure methods only, no LLM calls.

Tests: _parse_json_response, _extract_outermost_json, _merge_red_flags,
_extract_token_usage, and validation logic in analyze()."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.services.call_analyzer import CallAnalyzer
from app.models.schemas import CallAnalysis


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def setup_method(self):
        self.analyzer = CallAnalyzer()

    def test_valid_json(self):
        result = self.analyzer._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = self.analyzer._parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_with_plain_fences(self):
        text = '```\n{"key": "value"}\n```'
        result = self.analyzer._parse_json_response(text)
        assert result == {"key": "value"}

    def test_empty_string_returns_empty_dict(self):
        assert self.analyzer._parse_json_response("") == {}

    def test_none_returns_empty_dict(self):
        assert self.analyzer._parse_json_response(None) == {}

    def test_whitespace_only_returns_empty_dict(self):
        assert self.analyzer._parse_json_response("   ") == {}

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = self.analyzer._parse_json_response(text)
        assert result == {"outer": {"inner": [1, 2, 3]}}

    def test_json_with_preamble_text(self):
        text = 'Here is the analysis:\n{"summary": "test"}'
        result = self.analyzer._parse_json_response(text)
        assert result.get("summary") == "test"

    def test_truncated_json_repaired(self):
        """Truncated JSON should attempt repair by closing braces."""
        text = '{"summary": "test call", "interest": "high'
        result = self.analyzer._parse_json_response(text)
        # Should at least not crash; may or may not parse successfully
        assert isinstance(result, dict)

    def test_invalid_json_no_braces(self):
        result = self.analyzer._parse_json_response("just some text")
        assert result == {}

    def test_json_with_escaped_quotes(self):
        text = '{"summary": "he said \\"hello\\" to me"}'
        result = self.analyzer._parse_json_response(text)
        assert "hello" in result.get("summary", "")


# ---------------------------------------------------------------------------
# _extract_outermost_json
# ---------------------------------------------------------------------------

class TestExtractOutermostJson:
    def test_simple_json_block(self):
        text = 'prefix {"key": "val"} suffix'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result == '{"key": "val"}'

    def test_nested_braces(self):
        text = '{"outer": {"inner": "val"}}'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result == '{"outer": {"inner": "val"}}'

    def test_no_braces_returns_none(self):
        assert CallAnalyzer._extract_outermost_json("no json here") is None

    def test_braces_in_strings_ignored(self):
        text = '{"text": "this has {braces} inside"}'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result == text

    def test_unbalanced_returns_none(self):
        text = '{"key": "val"'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result is None

    def test_escaped_quotes_handled(self):
        text = '{"text": "he said \\"hi\\"", "num": 1}'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result is not None

    def test_multiple_json_blocks_returns_first(self):
        text = '{"a": 1} {"b": 2}'
        result = CallAnalyzer._extract_outermost_json(text)
        assert result == '{"a": 1}'


# ---------------------------------------------------------------------------
# _merge_red_flags
# ---------------------------------------------------------------------------

class TestMergeRedFlags:
    def setup_method(self):
        self.analyzer = CallAnalyzer()

    def test_empty_both(self):
        assert self.analyzer._merge_red_flags([], []) == []

    def test_only_realtime(self):
        rt = [{"id": "dnd", "severity": "critical", "evidence": "stop calling"}]
        result = self.analyzer._merge_red_flags(rt, [])
        assert len(result) == 1
        assert result[0]["id"] == "dnd"

    def test_only_postcard(self):
        pc = [{"id": "complaint", "severity": "high", "evidence": "file complaint"}]
        result = self.analyzer._merge_red_flags([], pc)
        assert len(result) == 1
        assert result[0]["id"] == "complaint"

    def test_dedup_same_id_keeps_realtime(self):
        rt = [{"id": "dnd", "severity": "critical", "evidence": "stop calling", "turn_index": 3}]
        pc = [{"id": "dnd", "severity": "critical", "evidence": "don't call again"}]
        result = self.analyzer._merge_red_flags(rt, pc)
        assert len(result) == 1
        assert result[0]["turn_index"] == 3  # from realtime
        assert result[0]["additional_evidence"] == "don't call again"

    def test_dedup_appends_postcard_evidence(self):
        rt = [{"id": "abuse", "severity": "high", "evidence": "rude words"}]
        pc = [{"id": "abuse", "severity": "high", "evidence": "more rude words"}]
        result = self.analyzer._merge_red_flags(rt, pc)
        assert result[0]["additional_evidence"] == "more rude words"

    def test_different_ids_both_kept(self):
        rt = [{"id": "dnd", "severity": "critical", "evidence": "a"}]
        pc = [{"id": "complaint", "severity": "high", "evidence": "b"}]
        result = self.analyzer._merge_red_flags(rt, pc)
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"dnd", "complaint"}

    def test_postcard_without_evidence_no_additional(self):
        rt = [{"id": "dnd", "severity": "critical", "evidence": "stop"}]
        pc = [{"id": "dnd", "severity": "critical"}]  # no evidence key
        result = self.analyzer._merge_red_flags(rt, pc)
        assert len(result) == 1
        assert "additional_evidence" not in result[0]

    def test_multiple_realtime_multiple_postcard(self):
        rt = [
            {"id": "a", "severity": "high", "evidence": "ea"},
            {"id": "b", "severity": "low", "evidence": "eb"},
        ]
        pc = [
            {"id": "b", "severity": "low", "evidence": "eb_post"},
            {"id": "c", "severity": "medium", "evidence": "ec"},
        ]
        result = self.analyzer._merge_red_flags(rt, pc)
        assert len(result) == 3
        b_flag = next(r for r in result if r["id"] == "b")
        assert b_flag["evidence"] == "eb"  # realtime kept
        assert b_flag["additional_evidence"] == "eb_post"

    def test_preserves_order(self):
        rt = [{"id": "first", "severity": "high", "evidence": "1"}]
        pc = [{"id": "second", "severity": "low", "evidence": "2"}]
        result = self.analyzer._merge_red_flags(rt, pc)
        assert result[0]["id"] == "first"
        assert result[1]["id"] == "second"


# ---------------------------------------------------------------------------
# _extract_token_usage
# ---------------------------------------------------------------------------

class TestExtractTokenUsage:
    def setup_method(self):
        self.analyzer = CallAnalyzer()

    def test_with_usage_metadata(self):
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=50,
            )
        )
        result = self.analyzer._extract_token_usage(response)
        assert result == {"input_tokens": 100, "output_tokens": 50}

    def test_no_usage_metadata(self):
        response = SimpleNamespace()
        result = self.analyzer._extract_token_usage(response)
        assert result == {"input_tokens": 0, "output_tokens": 0}

    def test_none_counts(self):
        response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=None,
                candidates_token_count=None,
            )
        )
        result = self.analyzer._extract_token_usage(response)
        assert result == {"input_tokens": 0, "output_tokens": 0}

    def test_exception_in_metadata_returns_zeros(self):
        """If something weird happens, should not crash."""
        response = "not an object"
        result = self.analyzer._extract_token_usage(response)
        assert result == {"input_tokens": 0, "output_tokens": 0}


# ---------------------------------------------------------------------------
# analyze() — validation logic (mocked LLM)
# ---------------------------------------------------------------------------

class TestAnalyzeValidation:
    def setup_method(self):
        self.analyzer = CallAnalyzer()

    @pytest.mark.asyncio
    async def test_empty_transcript_returns_empty(self):
        result = await self.analyzer.analyze([], None, "")
        assert isinstance(result, CallAnalysis)
        assert result.summary is None
        assert result.goal_outcome is None

    @pytest.mark.asyncio
    async def test_none_transcript_treated_as_empty(self):
        """None transcript should return empty CallAnalysis."""
        result = await self.analyzer.analyze(None, None, "")
        assert result.red_flags == []
        assert result.captured_data == {}


# ---------------------------------------------------------------------------
# Validation logic (sentiment, lead_temperature, buying_signals, sentiment_score)
# ---------------------------------------------------------------------------

class TestAnalyzeFieldValidation:
    """Test validation logic applied during analyze() to LLM output fields.

    We mock _analyze_outcome and _extract_structured_data to feed controlled
    dicts through the validation logic in analyze().
    """

    def setup_method(self):
        self.analyzer = CallAnalyzer()
        self._goal_config = {
            "goal_type": "book_meeting",
            "goal_description": "test",
            "success_criteria": [{"id": "booked", "label": "Meeting booked", "is_primary": True}],
        }
        self._extraction_result = {
            "red_flags": [], "captured_data": {}, "objections": None,
            "input_tokens": 0, "output_tokens": 0,
        }

    def _make_outcome(self, **overrides):
        base = {
            "goal_outcome": "confirmed",
            "summary": "test",
            "interest_level": "high",
            "input_tokens": 0,
            "output_tokens": 0,
        }
        base.update(overrides)
        return base

    async def _run_analyze(self, outcome_overrides):
        outcome = self._make_outcome(**outcome_overrides)
        with patch.object(self.analyzer, "_analyze_outcome", new_callable=AsyncMock, return_value=outcome), \
             patch.object(self.analyzer, "_extract_structured_data", new_callable=AsyncMock, return_value=self._extraction_result):
            return await self.analyzer.analyze(
                [{"role": "user", "content": "hi"}],
                self._goal_config, "system prompt",
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sentiment", ["positive", "neutral", "negative"])
    async def test_valid_sentiment_kept(self, sentiment):
        result = await self._run_analyze({"sentiment": sentiment})
        assert result.sentiment == sentiment

    @pytest.mark.asyncio
    async def test_invalid_sentiment_becomes_none(self):
        result = await self._run_analyze({"sentiment": "excited"})
        assert result.sentiment is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("temp", ["hot", "warm", "cold", "dead"])
    async def test_valid_lead_temperature_kept(self, temp):
        result = await self._run_analyze({"lead_temperature": temp})
        assert result.lead_temperature == temp

    @pytest.mark.asyncio
    async def test_invalid_lead_temperature_becomes_none(self):
        result = await self._run_analyze({"lead_temperature": "lukewarm"})
        assert result.lead_temperature is None

    @pytest.mark.asyncio
    async def test_buying_signals_list_kept(self):
        result = await self._run_analyze({"buying_signals": ["price inquiry", "timeline"]})
        assert result.buying_signals == ["price inquiry", "timeline"]

    @pytest.mark.asyncio
    async def test_buying_signals_non_list_becomes_none(self):
        result = await self._run_analyze({"buying_signals": "not a list"})
        assert result.buying_signals is None

    @pytest.mark.asyncio
    async def test_sentiment_score_clamped_to_range(self):
        result = await self._run_analyze({"sentiment_score": 15})
        assert result.sentiment_score == 10

    @pytest.mark.asyncio
    async def test_sentiment_score_non_int_becomes_none(self):
        result = await self._run_analyze({"sentiment_score": "high"})
        assert result.sentiment_score is None
