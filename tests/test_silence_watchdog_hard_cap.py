"""Tests for SilenceWatchdog hard cap on 'Hello? Can you hear me?' prompts.

The watchdog's escalation resets when the user speaks, allowing infinite
hello-loop cycles. These tests verify that a hard `max_prompts` counter
(which NEVER resets) prevents more than N prompts per call.
"""

from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports (same pattern as test_termination_source.py)
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)


class _FakeFrameProcessor:
    """Minimal stand-in for pipecat FrameProcessor."""

    def __init__(self, *, name="", **kwargs):
        self.name = name
        self._pushed_frames: list = []

    async def push_frame(self, frame, direction=None):
        self._pushed_frames.append(frame)

    async def process_frame(self, frame, direction):
        pass

    def create_task(self, coro):
        return asyncio.ensure_future(coro)

    async def cancel_task(self, task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def cleanup(self):
        pass


class _FakeFrame:
    pass

class _FakeTranscriptionFrame(_FakeFrame):
    def __init__(self, text=""):
        self.text = text

class _FakeEndFrame(_FakeFrame):
    pass

class _FakeBotStartedSpeakingFrame(_FakeFrame):
    pass

class _FakeBotStoppedSpeakingFrame(_FakeFrame):
    pass

class _FakeTTSSpeakFrame(_FakeFrame):
    def __init__(self, text=""):
        self.text = text

class _FakeCancelFrame(_FakeFrame):
    pass

class _FakeUserStartedSpeakingFrame(_FakeFrame):
    pass


_frames_mod = SimpleNamespace(
    EndFrame=_FakeEndFrame,
    TranscriptionFrame=_FakeTranscriptionFrame,
    BotStartedSpeakingFrame=_FakeBotStartedSpeakingFrame,
    BotStoppedSpeakingFrame=_FakeBotStoppedSpeakingFrame,
    TTSSpeakFrame=_FakeTTSSpeakFrame,
    CancelFrame=_FakeCancelFrame,
    Frame=_FakeFrame,
    UserStartedSpeakingFrame=_FakeUserStartedSpeakingFrame,
    StartFrame=type("StartFrame", (_FakeFrame,), {}),
)

_frame_processor_mod = SimpleNamespace(
    FrameDirection=SimpleNamespace(DOWNSTREAM="downstream", UPSTREAM="upstream"),
    FrameProcessor=_FakeFrameProcessor,
)

for mod in [
    "pipecat", "pipecat.frames",
    "pipecat.processors", "pipecat.processors.frame_processor",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.modules["pipecat.frames.frames"] = _frames_mod
sys.modules["pipecat.processors.frame_processor"] = _frame_processor_mod

# Force re-import with our stubs
sys.modules.pop("app.pipeline.silence_watchdog", None)
from app.pipeline.silence_watchdog import SilenceWatchdog

DOWNSTREAM = "downstream"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watchdog(**overrides) -> SilenceWatchdog:
    defaults = dict(timeout=15.0, call_sid="test-sid", max_prompts=2)
    defaults.update(overrides)
    return SilenceWatchdog(**defaults)


async def _send_frame(wd: SilenceWatchdog, frame):
    """Push a frame through the watchdog's process_frame."""
    await wd.process_frame(frame, DOWNSTREAM)


async def _simulate_bot_greeting(wd: SilenceWatchdog):
    """Simulate bot greeting to start the watchdog."""
    await _send_frame(wd, _FakeBotStartedSpeakingFrame())
    await _send_frame(wd, _FakeBotStoppedSpeakingFrame())


async def _simulate_user_speech(wd: SilenceWatchdog, text: str = "hello"):
    """Simulate user speaking (resets escalation)."""
    await _send_frame(wd, _FakeUserStartedSpeakingFrame())
    await _send_frame(wd, _FakeTranscriptionFrame(text=text))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWatchdogHardCap:
    """Tests for max_prompts hard cap on silence watchdog."""

    def test_default_max_prompts_is_2(self):
        wd = SilenceWatchdog(call_sid="test")
        assert wd._max_prompts == 2

    def test_total_prompts_starts_at_zero(self):
        wd = _make_watchdog()
        assert wd._total_prompts == 0

    def test_custom_max_prompts(self):
        wd = _make_watchdog(max_prompts=5)
        assert wd._max_prompts == 5

    @pytest.mark.asyncio
    async def test_first_timeout_sends_prompt(self):
        """After first timeout, watchdog pushes 'Hello? Can you hear me?'"""
        wd = _make_watchdog(timeout=0.5)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)
        # Watchdog polls every 1s, timeout is 0.5s → fires on first poll
        await asyncio.sleep(1.5)

        tts_frames = [f for f in wd._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]
        assert len(tts_frames) >= 1
        assert "Hello" in tts_frames[0].text or "hear me" in tts_frames[0].text
        assert wd._total_prompts == 1

    @pytest.mark.asyncio
    async def test_user_speech_resets_escalation_not_total(self):
        """User speech resets _escalation to 0 but _total_prompts stays."""
        wd = _make_watchdog()

        # Simulate: watchdog has fired once
        wd._escalation = 1
        wd._total_prompts = 1

        # User speaks
        await _simulate_user_speech(wd, "hello")

        assert wd._escalation == 0, "_escalation should reset on user speech"
        assert wd._total_prompts == 1, "_total_prompts should NOT reset on user speech"

    @pytest.mark.asyncio
    async def test_hard_cap_prevents_third_prompt(self):
        """After 2 prompt cycles with user-speech resets, 3rd timeout → goodbye."""
        wd = _make_watchdog(timeout=0.5, max_prompts=2)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)

        # First timeout → prompt (poll at 1s, timeout 0.5s)
        await asyncio.sleep(1.5)
        assert wd._total_prompts == 1

        # User responds → escalation resets
        await _simulate_user_speech(wd, "hello")
        assert wd._escalation == 0
        assert wd._total_prompts == 1

        # Second timeout → prompt
        await asyncio.sleep(1.5)
        assert wd._total_prompts == 2

        # User responds → escalation resets
        await _simulate_user_speech(wd, "hello")
        assert wd._escalation == 0
        assert wd._total_prompts == 2

        # Third timeout → should go to goodbye (cap reached), NOT another prompt
        wd._pushed_frames.clear()
        await asyncio.sleep(1.5)

        # Should have goodbye text, not another "Hello?"
        tts_frames = [f for f in wd._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]
        if tts_frames:
            # Last TTS should be goodbye, not prompt
            assert "take care" in tts_frames[-1].text.lower() or "try again" in tts_frames[-1].text.lower(), \
                f"Expected goodbye but got: {tts_frames[-1].text}"

    @pytest.mark.asyncio
    async def test_max_prompts_zero_goes_straight_to_goodbye(self):
        """max_prompts=0 means first timeout goes directly to goodbye."""
        wd = _make_watchdog(timeout=0.5, max_prompts=0)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)
        await asyncio.sleep(1.5)

        # Should never have sent a "Hello?" prompt
        tts_frames = [f for f in wd._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]
        hello_frames = [f for f in tts_frames if "hello" in f.text.lower() and "hear me" in f.text.lower()]
        assert len(hello_frames) == 0, "max_prompts=0 should skip prompts entirely"
        assert wd._total_prompts == 0

    @pytest.mark.asyncio
    async def test_bot_speaking_pauses_timer(self):
        """Timer doesn't fire while bot is speaking."""
        wd = _make_watchdog(timeout=0.5)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)

        # Bot starts speaking again immediately
        await _send_frame(wd, _FakeBotStartedSpeakingFrame())
        assert wd._bot_speaking is True

        # Wait longer than timeout + poll interval
        await asyncio.sleep(2.0)

        # Should not have fired (bot was speaking the whole time)
        assert wd._escalation == 0
        assert wd._total_prompts == 0

    @pytest.mark.asyncio
    async def test_echo_during_bot_speech_no_reset(self):
        """Transcription during bot speech doesn't reset escalation."""
        wd = _make_watchdog()
        wd._escalation = 1
        wd._total_prompts = 1
        wd._bot_speaking = True

        # Echo transcript while bot is speaking
        await _send_frame(wd, _FakeTranscriptionFrame(text="echo words"))

        assert wd._escalation == 1, "Echo during bot speech should NOT reset escalation"
        assert wd._total_prompts == 1

    @pytest.mark.asyncio
    async def test_second_timeout_without_speech_hangs_up(self):
        """Without user speech between timeouts, escalation 2 → hangup."""
        wd = _make_watchdog(timeout=0.5)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        wd.set_task(mock_task)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)

        # Wait for first timeout (poll at 1s) + second timeout (poll at 2s) + goodbye sleep (4s)
        await asyncio.sleep(7.0)

        # Should have pushed goodbye + EndFrame via task
        tts_frames = [f for f in wd._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]
        goodbye_frames = [f for f in tts_frames if "take care" in f.text.lower() or "try again" in f.text.lower()]
        assert len(goodbye_frames) >= 1, "Should have sent goodbye message"

    @pytest.mark.asyncio
    async def test_watchdog_cap_immediate_goodbye(self):
        """When cap is reached, goodbye fires in the same loop iteration (elif→if fix)."""
        wd = _make_watchdog(timeout=0.5, max_prompts=1)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        wd.set_task(mock_task)
        wd._pushed_frames = []

        await _simulate_bot_greeting(wd)

        # First timeout → prompt (poll at 1s, total=1, at cap)
        await asyncio.sleep(1.5)
        assert wd._total_prompts == 1

        # User responds
        await _simulate_user_speech(wd, "hello")

        wd._pushed_frames.clear()
        # Second timeout → should go DIRECTLY to goodbye (cap reached)
        await asyncio.sleep(1.5)

        tts_frames = [f for f in wd._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]
        if tts_frames:
            texts = [f.text.lower() for f in tts_frames]
            has_goodbye = any("take care" in t or "try again" in t for t in texts)
            has_prompt = any("hello" in t and "hear me" in t for t in texts)
            assert has_goodbye, f"Expected goodbye, got: {texts}"
            assert not has_prompt, "Should not prompt again after cap"
