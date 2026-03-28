"""Test that HelloGuard is wired into the pipeline."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Fake FrameProcessor base class
class _FakeFrameProcessor:
    def __init__(self, *, name="", **kwargs):
        self.name = name
    async def push_frame(self, frame, direction=None):
        pass
    async def process_frame(self, frame, direction):
        pass
    def create_task(self, coro):
        import asyncio
        return asyncio.ensure_future(coro)
    async def cancel_task(self, task):
        task.cancel()
    async def cleanup(self):
        pass

_frame_processor_mod = SimpleNamespace(
    FrameDirection=SimpleNamespace(DOWNSTREAM="downstream", UPSTREAM="upstream"),
    FrameProcessor=_FakeFrameProcessor,
)

_base_output_mock = MagicMock()
_base_output_mock.BOT_VAD_STOP_SECS = 1.5

# Mock ALL pipecat submodules
for mod in [
    "pipecat", "pipecat.frames", "pipecat.frames.frames",
    "pipecat.processors", "pipecat.processors.aggregators",
    "pipecat.processors.aggregators.openai_llm_context",
    "pipecat.transports", "pipecat.transports.base_output",
    "pipecat.transports.websocket", "pipecat.transports.websocket.fastapi",
    "pipecat.audio", "pipecat.audio.vad", "pipecat.audio.vad.silero",
    "pipecat.audio.vad.vad_analyzer",
    "pipecat.audio.interruptions", "pipecat.audio.interruptions.min_words_interruption_strategy",
    "pipecat.audio.turn", "pipecat.audio.turn.smart_turn",
    "pipecat.audio.turn.smart_turn.base_smart_turn",
    "pipecat.audio.turn.smart_turn.local_smart_turn_v3",
    "pipecat.turns", "pipecat.turns.user_stop", "pipecat.turns.user_turn_strategies",
    "pipecat.pipeline", "pipecat.pipeline.pipeline", "pipecat.pipeline.runner",
    "pipecat.pipeline.task",
    "pipecat.services", "pipecat.services.google", "pipecat.services.google.llm",
    "pipecat.services.google.llm_vertex",
    "pipecat.services.deepgram", "pipecat.services.deepgram.stt",
    "pipecat.services.sarvam", "pipecat.services.elevenlabs", "pipecat.services.smallest",
    "pipecat.serializers", "pipecat.serializers.base_serializer",
    "pipecat.adapters",
    "deepgram",
    "starlette", "starlette.websockets",
    "app.pipeline.call_guard", "app.pipeline.silence_watchdog",
    "app.pipeline.phrase_aggregator",
    "app.serializers", "app.serializers.plivo_pcm",
    "app.services.gemini_llm_service",
    "app.models.bot_config", "app.models.schemas",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.modules["pipecat.processors.frame_processor"] = _frame_processor_mod
sys.modules["pipecat.transports.base_output"] = _base_output_mock

sys.modules.pop("app.pipeline.factory", None)

from app.pipeline.factory import HelloGuard


def test_hello_guard_class_exists():
    """HelloGuard class is importable and has the expected interface."""
    guard = HelloGuard(call_sid="test")
    assert hasattr(guard, "_bot_speaking")
    assert hasattr(guard, "_pending_llm")
    assert hasattr(guard, "_suppressed_hello")
    # After backchannel expansion, should have these word sets
    assert hasattr(HelloGuard, "_HELLO_WORDS")
    assert hasattr(HelloGuard, "_PURE_BACKCHANNELS")
    assert hasattr(HelloGuard, "_AFFIRMATIVE_TOKENS")
    assert hasattr(HelloGuard, "_STOP_WORDS")
    assert hasattr(guard, "_should_suppress")
