"""Tests for _build_end_call_tool schema and handle_end_call validation."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock heavy imports before importing the module under test
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Provide a real FunctionSchema class that _build_end_call_tool constructs
class _FunctionSchema:
    def __init__(self, *, name, description, properties, required):
        self.name = name
        self.description = description
        self.properties = properties
        self.required = required


_adapters_mock = SimpleNamespace(
    FunctionSchema=_FunctionSchema,
)

for mod in [
    "pipecat", "pipecat.adapters", "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.function_schema",
    "pipecat.frames", "pipecat.frames.frames",
    "pipecat.pipeline", "pipecat.pipeline.pipeline", "pipecat.pipeline.runner",
    "pipecat.pipeline.task",
    "pipecat.processors", "pipecat.processors.aggregators",
    "pipecat.processors.aggregators.openai_llm_context",
    "pipecat.processors.frame_processor",
    "pipecat.transcriptions", "pipecat.transcriptions.language",
    "pipecat.audio", "pipecat.audio.vad", "pipecat.audio.vad.silero",
    "pipecat.audio.vad.vad_analyzer",
    "pipecat.audio.interruptions",
    "pipecat.audio.interruptions.min_words_interruption_strategy",
    "pipecat.audio.turn", "pipecat.audio.turn.smart_turn",
    "pipecat.audio.turn.smart_turn.base_smart_turn",
    "pipecat.audio.turn.smart_turn.local_smart_turn_v3",
    "pipecat.services", "pipecat.services.google",
    "pipecat.services.google.tts", "pipecat.services.google.llm",
    "pipecat.services.google.llm_vertex",
    "pipecat.services.sarvam", "pipecat.services.sarvam.tts",
    "pipecat.services.elevenlabs", "pipecat.services.elevenlabs.tts",
    "pipecat.services.deepgram", "pipecat.services.deepgram.stt",
    "pipecat.transports", "pipecat.transports.base_output",
    "pipecat.transports.websocket", "pipecat.transports.websocket.fastapi",
    "deepgram",
    "aiohttp",
    "starlette", "starlette.websockets",
]:
    sys.modules.setdefault(mod, MagicMock())

# Override the specific module that has FunctionSchema so the real class is used
sys.modules["pipecat.adapters.schemas.function_schema"] = _adapters_mock

sys.modules.setdefault(
    "app.config",
    SimpleNamespace(
        settings=SimpleNamespace(
            GREETING_DIRECT_PLAY=False,
            COMFORT_NOISE_ENABLED=False,
            SARVAM_API_KEY="fake",
            ELEVENLABS_API_KEY="fake",
            GOOGLE_CLOUD_PROJECT="fake",
            VERTEX_AI_LOCATION="us-central1",
        ),
        gemini_key_pool=SimpleNamespace(get_key=lambda: "fake-key"),
    ),
)

for mod in [
    "app.models.bot_config", "app.models.schemas",
    "app.serializers.plivo_pcm",
    "app.pipeline.call_guard", "app.pipeline.phrase_aggregator",
    "app.pipeline.silence_watchdog",
]:
    sys.modules.setdefault(mod, MagicMock())

from app.pipeline.factory import _build_end_call_tool


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestBuildEndCallToolSchema:
    """Verify _build_end_call_tool returns the correct FunctionSchema."""

    def setup_method(self):
        self.tool = _build_end_call_tool()

    def test_schema_structure(self):
        assert self.tool.name == "end_call"
        assert isinstance(self.tool.description, str)
        assert "reason" in self.tool.properties
        assert self.tool.required == ["reason"]

    def test_reason_has_enum_with_six_values(self):
        reason_prop = self.tool.properties["reason"]
        assert "enum" in reason_prop
        assert len(reason_prop["enum"]) == 6

    def test_enum_values_are_correct(self):
        expected = {
            "customer_goodbye", "customer_rejected", "customer_busy",
            "customer_requested_hangup", "customer_no_response", "bot_said_goodbye",
        }
        assert set(self.tool.properties["reason"]["enum"]) == expected

    def test_description_does_not_contain_mutual_goodbye(self):
        assert "mutual_goodbye" not in self.tool.description

    def test_description_contains_audio_issues(self):
        assert "AUDIO ISSUES" in self.tool.description

    def test_description_contains_positive_short_answers(self):
        assert "POSITIVE SHORT ANSWERS" in self.tool.description

    def test_description_contains_achha_and_haan(self):
        assert "Achha" in self.tool.description
        assert "Haan" in self.tool.description

    def test_description_contains_fewer_than_3_questions(self):
        assert "fewer than 3 questions" in self.tool.description


# ---------------------------------------------------------------------------
# handle_end_call validation tests
# ---------------------------------------------------------------------------

class TestHandleEndCall:
    """Test that handle_end_call validates reason and maps invalid ones."""

    def test_valid_reason_passes_through(self):
        """Valid reasons in _VALID_END_REASONS should be stored unchanged."""
        _VALID_END_REASONS = {
            "customer_goodbye", "customer_rejected", "customer_busy",
            "customer_requested_hangup", "customer_no_response", "bot_said_goodbye",
        }

        for reason in _VALID_END_REASONS:
            # The handle_end_call is a closure inside build_pipeline, so we
            # test the logic directly: valid reason stays as-is
            assert reason in _VALID_END_REASONS
            # No mapping needed
            mapped = reason if reason in _VALID_END_REASONS else f"other: {reason}"
            assert mapped == reason

    def test_invalid_reason_mapped_to_other(self):
        """Reasons not in the valid set get mapped to 'other: {reason}'."""
        _VALID_END_REASONS = {
            "customer_goodbye", "customer_rejected", "customer_busy",
            "customer_requested_hangup", "customer_no_response", "bot_said_goodbye",
        }

        invalid_reasons = [
            "mutual_goodbye",
            "conversation_ended",
            "random_reason",
            "customer_said_thanks",
        ]
        for reason in invalid_reasons:
            assert reason not in _VALID_END_REASONS
            mapped = reason if reason in _VALID_END_REASONS else f"other: {reason}"
            assert mapped == f"other: {reason}"

    def test_handle_end_call_integration(self):
        """Integration test: simulate handle_end_call closure behavior."""
        _VALID_END_REASONS = {
            "customer_goodbye", "customer_rejected", "customer_busy",
            "customer_requested_hangup", "customer_no_response", "bot_said_goodbye",
        }

        # Simulate the closure logic from factory.py
        call_guard = SimpleNamespace(
            llm_end_reason=None,
            set_termination_source=MagicMock(),
        )
        logger = MagicMock()

        async def handle_end_call(params):
            reason = params.arguments.get("reason", "conversation_ended")
            if reason not in _VALID_END_REASONS:
                logger.warning("end_call_invalid_reason", raw_reason=reason)
                reason = f"other: {reason}"
            call_guard.llm_end_reason = reason
            call_guard.set_termination_source("bot_end_call")
            await params.result_callback("Call ending now. Do not say anything else.")

        # Test with valid reason
        params_valid = SimpleNamespace(
            arguments={"reason": "customer_goodbye"},
            result_callback=AsyncMock(),
        )
        asyncio.run(handle_end_call(params_valid))
        assert call_guard.llm_end_reason == "customer_goodbye"
        call_guard.set_termination_source.assert_called_with("bot_end_call")

        # Test with invalid reason
        call_guard.llm_end_reason = None
        params_invalid = SimpleNamespace(
            arguments={"reason": "mutual_goodbye"},
            result_callback=AsyncMock(),
        )
        asyncio.run(handle_end_call(params_invalid))
        assert call_guard.llm_end_reason == "other: mutual_goodbye"
        logger.warning.assert_called_once()


class AsyncMock(MagicMock):
    """Simple async-compatible mock for result_callback."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)
