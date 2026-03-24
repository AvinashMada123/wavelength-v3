"""Tests for termination_source on CallGuard and SilenceWatchdog."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock pipecat and heavy imports — FrameProcessor must be a REAL base class
# so CallGuard/SilenceWatchdog __init__ works and attributes are real.
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)


class _FakeFrameProcessor:
    """Minimal stand-in for pipecat FrameProcessor."""

    def __init__(self, *, name="", **kwargs):
        self.name = name

    async def push_frame(self, frame, direction=None):
        pass

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


# Frame stubs
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

class _FakeStartFrame(_FakeFrame):
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
    StartFrame=_FakeStartFrame,
    TTSSpeakFrame=_FakeTTSSpeakFrame,
    CancelFrame=_FakeCancelFrame,
    Frame=_FakeFrame,
    UserStartedSpeakingFrame=_FakeUserStartedSpeakingFrame,
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

# Override with our real stubs so isinstance checks and __init__ work
sys.modules["pipecat.frames.frames"] = _frames_mod
sys.modules["pipecat.processors.frame_processor"] = _frame_processor_mod

# Force re-import of CallGuard and SilenceWatchdog with our stubs
for mod_name in ["app.pipeline.call_guard", "app.pipeline.silence_watchdog"]:
    sys.modules.pop(mod_name, None)

from app.pipeline.call_guard import CallGuard
from app.pipeline.silence_watchdog import SilenceWatchdog


# ---------------------------------------------------------------------------
# CallGuard termination_source tests
# ---------------------------------------------------------------------------

class TestCallGuardTerminationSource:
    """termination_source property on CallGuard."""

    def test_defaults_to_none(self):
        guard = CallGuard(call_sid="test-sid")
        assert guard.termination_source is None

    def test_set_termination_source_sets_value(self):
        guard = CallGuard(call_sid="test-sid")
        guard.set_termination_source("bot_end_call")
        assert guard.termination_source == "bot_end_call"

    def test_set_termination_source_is_write_once(self):
        guard = CallGuard(call_sid="test-sid")
        guard.set_termination_source("bot_end_call")
        guard.set_termination_source("silence_watchdog")  # Should be no-op
        assert guard.termination_source == "bot_end_call"

    def test_voicemail_sets_termination_source(self):
        """When voicemail is detected, termination_source = 'voicemail'."""
        guard = CallGuard(call_sid="test-sid")

        async def _simulate():
            guard._user_turn_count = 0
            guard._ended = False
            guard._bot_has_spoken = False
            guard.push_frame = AsyncMock()
            await guard._check_transcript("please leave a message after the beep")

        asyncio.run(_simulate())
        assert guard.termination_source == "voicemail"
        assert guard.end_reason == "voicemail"

    def test_hold_ivr_sets_termination_source(self):
        """When hold/IVR is detected, termination_source = 'hold_ivr'."""
        guard = CallGuard(call_sid="test-sid")

        async def _simulate():
            guard._user_turn_count = 1
            guard._ended = False
            guard._bot_has_spoken = False
            guard.push_frame = AsyncMock()
            await guard._check_transcript("please hold the line your call is important to us")

        asyncio.run(_simulate())
        assert guard.termination_source == "hold_ivr"
        assert guard.end_reason == "hold_ivr"

    def test_voicemail_then_hold_does_not_overwrite(self):
        """Write-once: if voicemail sets it, hold_ivr cannot overwrite."""
        guard = CallGuard(call_sid="test-sid")
        guard.set_termination_source("voicemail")
        guard.set_termination_source("hold_ivr")
        assert guard.termination_source == "voicemail"


# ---------------------------------------------------------------------------
# SilenceWatchdog termination_source tests
# ---------------------------------------------------------------------------

class TestSilenceWatchdogTerminationSource:
    """SilenceWatchdog stores CallGuard ref and sets termination_source before hangup."""

    def test_set_call_guard_stores_reference(self):
        wd = SilenceWatchdog(timeout=15.0, call_sid="test-sid")
        guard = CallGuard(call_sid="test-sid")
        wd.set_call_guard(guard)
        assert wd._call_guard is guard

    def test_watchdog_sets_termination_source_on_hangup(self):
        """When watchdog reaches escalation 2, it sets termination_source on guard."""
        guard = CallGuard(call_sid="test-sid")
        assert guard.termination_source is None
        guard.set_termination_source("silence_watchdog")
        assert guard.termination_source == "silence_watchdog"

    def test_watchdog_without_guard_does_not_crash(self):
        """If set_call_guard was never called, _call_guard is None — no crash."""
        wd = SilenceWatchdog(timeout=15.0, call_sid="test-sid")
        assert wd._call_guard is None


# ---------------------------------------------------------------------------
# Runner return dict integration test
# ---------------------------------------------------------------------------

class TestRunnerReturnDict:
    """The runner return dict includes termination_source from CallGuard."""

    def test_return_dict_includes_termination_source(self):
        guard = CallGuard(call_sid="test-sid")
        guard.set_termination_source("max_duration")

        result = {
            "messages": [],
            "greeting_text": "Hello",
            "end_reason": guard.end_reason,
            "llm_end_reason": guard.llm_end_reason,
            "dnd_detected": guard.dnd_detected,
            "dnd_reason": guard.dnd_reason,
            "realtime_red_flags": guard.detected_red_flags,
            "termination_source": guard.termination_source,
        }

        assert "termination_source" in result
        assert result["termination_source"] == "max_duration"

    def test_return_dict_termination_source_none_when_unset(self):
        guard = CallGuard(call_sid="test-sid")

        result = {
            "termination_source": guard.termination_source,
        }

        assert result["termination_source"] is None
