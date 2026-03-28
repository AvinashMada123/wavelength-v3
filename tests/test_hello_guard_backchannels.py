"""Tests for HelloGuard backchannel suppression.

HelloGuard suppresses short utterances during bot speech to prevent
backchannels ('hmm', 'yeah', 'okay') from killing the bot's response.

Word tiers:
- HELLO_WORDS: always suppressed during bot_speaking or pending_llm
- PURE_BACKCHANNELS: always suppressed during bot_speaking or pending_llm
- AFFIRMATIVE_TOKENS: suppressed during bot_speaking ONLY (not pending_llm)
- STOP_WORDS: NEVER suppressed — always pass through
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)


class _FakeFrameProcessor:
    def __init__(self, *, name="", **kwargs):
        self.name = name
        self._pushed_frames: list = []

    async def push_frame(self, frame, direction=None):
        self._pushed_frames.append(frame)

    async def process_frame(self, frame, direction):
        pass

    def create_task(self, coro):
        import asyncio
        return asyncio.ensure_future(coro)

    async def cancel_task(self, task):
        task.cancel()

    async def cleanup(self):
        pass


class _FakeFrame:
    pass

class _FakeTranscriptionFrame(_FakeFrame):
    def __init__(self, text=""):
        self.text = text

class _FakeBotStartedSpeakingFrame(_FakeFrame):
    pass

class _FakeBotStoppedSpeakingFrame(_FakeFrame):
    pass

class _FakeUserStartedSpeakingFrame(_FakeFrame):
    pass

class _FakeUserStoppedSpeakingFrame(_FakeFrame):
    pass

class _FakeStartFrame(_FakeFrame):
    pass


_frames_mod = SimpleNamespace(
    TranscriptionFrame=_FakeTranscriptionFrame,
    BotStartedSpeakingFrame=_FakeBotStartedSpeakingFrame,
    BotStoppedSpeakingFrame=_FakeBotStoppedSpeakingFrame,
    UserStartedSpeakingFrame=_FakeUserStartedSpeakingFrame,
    UserStoppedSpeakingFrame=_FakeUserStoppedSpeakingFrame,
    StartFrame=_FakeStartFrame,
    Frame=_FakeFrame,
    EndFrame=type("EndFrame", (_FakeFrame,), {}),
    TTSSpeakFrame=type("TTSSpeakFrame", (_FakeFrame,), {"__init__": lambda self, text="": setattr(self, "text", text) or None}),
    CancelFrame=type("CancelFrame", (_FakeFrame,), {}),
    TTSUpdateSettingsFrame=MagicMock(),
)

_frame_processor_mod = SimpleNamespace(
    FrameDirection=SimpleNamespace(DOWNSTREAM="downstream", UPSTREAM="upstream"),
    FrameProcessor=_FakeFrameProcessor,
)

# Mock ALL pipecat submodules that factory.py imports at the top level
_base_output_mock = MagicMock()
_base_output_mock.BOT_VAD_STOP_SECS = 1.5

for mod in [
    "pipecat", "pipecat.frames",
    "pipecat.processors", "pipecat.processors.frame_processor",
    "pipecat.processors.aggregators", "pipecat.processors.aggregators.openai_llm_context",
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

# Override with our real stubs
sys.modules["pipecat.frames.frames"] = _frames_mod
sys.modules["pipecat.processors.frame_processor"] = _frame_processor_mod
sys.modules["pipecat.transports.base_output"] = _base_output_mock

# Force re-import of factory with our stubs
sys.modules.pop("app.pipeline.factory", None)

from app.pipeline.factory import HelloGuard

DOWNSTREAM = "downstream"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard() -> HelloGuard:
    return HelloGuard(call_sid="test-sid")


async def _set_bot_speaking(guard: HelloGuard):
    """Simulate bot started speaking."""
    await guard.process_frame(_FakeBotStartedSpeakingFrame(), DOWNSTREAM)
    assert guard._bot_speaking is True


async def _set_bot_stopped(guard: HelloGuard):
    """Simulate bot stopped speaking."""
    await guard.process_frame(_FakeBotStoppedSpeakingFrame(), DOWNSTREAM)
    assert guard._bot_speaking is False


async def _set_pending_llm(guard: HelloGuard):
    """Simulate pending LLM (real transcript was sent, waiting for bot)."""
    guard._pending_llm = True
    guard._bot_speaking = False


async def _send_transcript(guard: HelloGuard, text: str) -> bool:
    """Send a TranscriptionFrame and return True if it was passed through."""
    guard._pushed_frames = []
    await guard.process_frame(_FakeTranscriptionFrame(text=text), DOWNSTREAM)
    return any(isinstance(f, _FakeTranscriptionFrame) for f in guard._pushed_frames)


# ---------------------------------------------------------------------------
# Tests: Suppression during bot speech
# ---------------------------------------------------------------------------

class TestSuppressionDuringBotSpeech:
    """Words suppressed while the bot is actively speaking."""

    @pytest.mark.asyncio
    async def test_hello_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "Hello?")
        assert not passed, "'hello' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_hmm_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "hmm")
        assert not passed, "'hmm' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_mm_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "mm")
        assert not passed, "'mm' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_yeah_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "yeah")
        assert not passed, "'yeah' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_okay_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "okay")
        assert not passed, "'okay' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_yes_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "yes")
        assert not passed, "'yes' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_hindi_haan_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "haan")
        assert not passed, "'haan' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_hindi_achha_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "achha")
        assert not passed, "'achha' should be suppressed during bot speech"

    @pytest.mark.asyncio
    async def test_hindi_ji_suppressed_during_bot_speech(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "ji")
        assert not passed, "'ji' should be suppressed during bot speech"


# ---------------------------------------------------------------------------
# Tests: Affirmative tokens during pending_llm (should NOT suppress)
# ---------------------------------------------------------------------------

class TestAffirmativesDuringPendingLLM:
    """Affirmative words pass through during pending_llm (could be real answers)."""

    @pytest.mark.asyncio
    async def test_yes_passes_during_pending_llm(self):
        guard = _make_guard()
        await _set_pending_llm(guard)
        passed = await _send_transcript(guard, "yes")
        assert passed, "'yes' should pass through during pending_llm"

    @pytest.mark.asyncio
    async def test_okay_passes_during_pending_llm(self):
        guard = _make_guard()
        await _set_pending_llm(guard)
        passed = await _send_transcript(guard, "okay")
        assert passed, "'okay' should pass through during pending_llm"

    @pytest.mark.asyncio
    async def test_haan_passes_during_pending_llm(self):
        guard = _make_guard()
        await _set_pending_llm(guard)
        passed = await _send_transcript(guard, "haan")
        assert passed, "'haan' should pass through during pending_llm"

    @pytest.mark.asyncio
    async def test_pure_backchannel_still_suppressed_during_pending_llm(self):
        """Pure backchannels (hmm, mm) are suppressed even during pending_llm."""
        guard = _make_guard()
        await _set_pending_llm(guard)
        passed = await _send_transcript(guard, "hmm")
        assert not passed, "'hmm' should be suppressed even during pending_llm"


# ---------------------------------------------------------------------------
# Tests: Stop words NEVER suppressed
# ---------------------------------------------------------------------------

class TestStopWordsNeverSuppressed:
    """Stop words always pass through regardless of pipeline state."""

    @pytest.mark.asyncio
    async def test_no_never_suppressed(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "no")
        assert passed, "'no' should NEVER be suppressed"

    @pytest.mark.asyncio
    async def test_wait_never_suppressed(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "wait")
        assert passed, "'wait' should NEVER be suppressed"

    @pytest.mark.asyncio
    async def test_stop_never_suppressed(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "stop")
        assert passed, "'stop' should NEVER be suppressed"

    @pytest.mark.asyncio
    async def test_ruko_never_suppressed(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "ruko")
        assert passed, "'ruko' should NEVER be suppressed"

    @pytest.mark.asyncio
    async def test_nahi_never_suppressed(self):
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "nahi")
        assert passed, "'nahi' should NEVER be suppressed"

    @pytest.mark.asyncio
    async def test_mixed_stop_and_backchannel(self):
        """'no okay' contains a stop word — should pass through."""
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "no okay")
        assert passed, "Mixed stop+backchannel should pass through"


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_backchannel_when_idle_passes_through(self):
        """When bot is NOT speaking and no pending LLM, everything passes."""
        guard = _make_guard()
        # Idle state: bot_speaking=False, pending_llm=False (defaults)
        passed = await _send_transcript(guard, "yeah")
        assert passed, "Backchannels should pass when pipeline is idle"

    @pytest.mark.asyncio
    async def test_multi_word_not_suppressed(self):
        """3+ words always pass through even during bot speech."""
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "yes okay sure")
        assert passed, "3+ words should always pass through"

    @pytest.mark.asyncio
    async def test_three_backchannels_pass_through(self):
        """'hmm hmm hmm' is 3 words — passes through despite all being backchannels."""
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "hmm hmm hmm")
        assert passed, "3+ backchannel words should pass (word count rule)"

    @pytest.mark.asyncio
    async def test_empty_transcript_passes_through(self):
        """Empty string passes through without error."""
        guard = _make_guard()
        await _set_bot_speaking(guard)
        passed = await _send_transcript(guard, "")
        assert passed, "Empty transcript should pass through"

    @pytest.mark.asyncio
    async def test_suppressed_drops_user_stopped_frame(self):
        """After suppressing transcript, UserStoppedSpeakingFrame is also dropped."""
        guard = _make_guard()
        await _set_bot_speaking(guard)

        # Send suppressed transcript
        await _send_transcript(guard, "hmm")
        assert guard._suppressed_hello is True

        # Now send UserStoppedSpeakingFrame
        guard._pushed_frames = []
        await guard.process_frame(_FakeUserStoppedSpeakingFrame(), DOWNSTREAM)

        stopped_frames = [f for f in guard._pushed_frames if isinstance(f, _FakeUserStoppedSpeakingFrame)]
        assert len(stopped_frames) == 0, "UserStoppedSpeakingFrame should be dropped after suppression"

    @pytest.mark.asyncio
    async def test_real_answer_after_bot_stops_passes_through(self):
        """Bot finishes speaking, user says 'yes' → passes through."""
        guard = _make_guard()
        await _set_bot_speaking(guard)
        await _set_bot_stopped(guard)
        # Pipeline is now idle
        passed = await _send_transcript(guard, "yes")
        assert passed, "'yes' after bot stops should pass through"

    @pytest.mark.asyncio
    async def test_should_suppress_returns_category(self):
        """_should_suppress method returns (bool, category) for logging."""
        guard = _make_guard()
        guard._bot_speaking = True

        should, category = guard._should_suppress("hello")
        assert should is True
        assert category == "hello"

        should, category = guard._should_suppress("hmm")
        assert should is True
        assert category == "pure_backchannel"

        should, category = guard._should_suppress("yes")
        assert should is True
        assert category == "affirmative_during_speech"

        should, category = guard._should_suppress("no")
        assert should is False
        assert category == "stop_word"

    @pytest.mark.asyncio
    async def test_multiple_transcription_frames_same_turn(self):
        """Two consecutive transcripts in same turn — both evaluated independently."""
        guard = _make_guard()
        await _set_bot_speaking(guard)

        # First: backchannel → suppressed
        passed1 = await _send_transcript(guard, "hmm")
        assert not passed1

        # Second: real speech → passes
        passed2 = await _send_transcript(guard, "actually I wanted to say something")
        assert passed2
