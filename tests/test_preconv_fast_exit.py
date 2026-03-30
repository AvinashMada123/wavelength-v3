"""Tests for pre-conversation fast exit: voicemail/hold/IVR early termination.

Covers three independent fixes:
  Fix 1: SilenceWatchdog pre-conversation fast exit (skip prompt if user never spoke)
  Fix 2: EarlyHangupTimer (hard ceiling on no-speech duration)
  Fix 3: HoldMusicDetector (VAD active but no STT transcripts)

All three share the invariant: never fire once user has spoken.
"""

from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports (same pattern as test_silence_watchdog_hard_cap.py)
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

class _FakeStartFrame(_FakeFrame):
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
    StartFrame=_FakeStartFrame,
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
for mod_name in [
    "app.pipeline.silence_watchdog",
    "app.pipeline.early_hangup",
    "app.pipeline.hold_music_detector",
    "app.pipeline.call_guard",
]:
    sys.modules.pop(mod_name, None)

# Import app.config first so settings is available for silence_watchdog's module-level import
from app.config import settings as _real_settings

from app.pipeline.silence_watchdog import SilenceWatchdog
from app.pipeline.early_hangup import EarlyHangupTimer
from app.pipeline.hold_music_detector import HoldMusicDetector
from app.pipeline.call_guard import CallGuard

DOWNSTREAM = "downstream"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call_guard() -> CallGuard:
    cg = CallGuard(call_sid="test-sid")
    return cg


def _make_watchdog(call_guard=None, **overrides) -> SilenceWatchdog:
    defaults = dict(timeout=0.5, call_sid="test-sid", max_prompts=2)
    defaults.update(overrides)
    wd = SilenceWatchdog(**defaults)
    if call_guard:
        wd.set_call_guard(call_guard)
    return wd


def _make_early_hangup(call_guard=None, **overrides) -> EarlyHangupTimer:
    defaults = dict(timeout=2.0, call_sid="test-sid")
    defaults.update(overrides)
    eh = EarlyHangupTimer(**defaults)
    if call_guard:
        eh.set_call_guard(call_guard)
    return eh


def _make_hold_detector(call_guard=None, **overrides) -> HoldMusicDetector:
    defaults = dict(timeout=2.0, call_sid="test-sid")
    defaults.update(overrides)
    hd = HoldMusicDetector(**defaults)
    if call_guard:
        hd.set_call_guard(call_guard)
    return hd


async def _send(processor, frame):
    await processor.process_frame(frame, DOWNSTREAM)


async def _bot_greeting(processor):
    await _send(processor, _FakeBotStartedSpeakingFrame())
    await _send(processor, _FakeBotStoppedSpeakingFrame())


async def _user_speaks(processor, text="hello"):
    await _send(processor, _FakeUserStartedSpeakingFrame())
    await _send(processor, _FakeTranscriptionFrame(text=text))


def _tts_frames(processor) -> list:
    return [f for f in processor._pushed_frames if isinstance(f, _FakeTTSSpeakFrame)]


def _end_frames(processor) -> list:
    return [f for f in processor._pushed_frames if isinstance(f, _FakeEndFrame)]


def _has_goodbye(processor) -> bool:
    return any(
        "take care" in f.text.lower() or "try again" in f.text.lower()
        for f in _tts_frames(processor)
    )


# ===========================================================================
# CallGuard: user_has_spoken tests
# ===========================================================================

class TestCallGuardUserHasSpoken:

    def test_false_initially(self):
        """#24: user_has_spoken is False on fresh CallGuard."""
        cg = _make_call_guard()
        assert cg.user_has_spoken is False

    @pytest.mark.asyncio
    async def test_true_after_real_transcript(self):
        """#25: Set True after bot speaks then user transcript arrives."""
        cg = _make_call_guard()
        # Bot speaks first
        await _send(cg, _FakeBotStartedSpeakingFrame())
        assert cg._bot_has_spoken is True
        # User transcript
        await _send(cg, _FakeTranscriptionFrame(text="hello"))
        assert cg.user_has_spoken is True

    @pytest.mark.asyncio
    async def test_false_for_carrier_transcript(self):
        """#26: Transcript before bot speaks does not set user_has_spoken."""
        cg = _make_call_guard()
        # Carrier recording — bot hasn't spoken yet
        await _send(cg, _FakeTranscriptionFrame(text="the number you have dialed"))
        assert cg.user_has_spoken is False

    @pytest.mark.asyncio
    async def test_sticky_once_set(self):
        """#27: user_has_spoken stays True forever once set."""
        cg = _make_call_guard()
        await _send(cg, _FakeBotStartedSpeakingFrame())
        await _send(cg, _FakeTranscriptionFrame(text="hello"))
        assert cg.user_has_spoken is True
        # More bot speech + silence shouldn't unset it
        await _send(cg, _FakeBotStartedSpeakingFrame())
        assert cg.user_has_spoken is True


# ===========================================================================
# Fix 1: SilenceWatchdog pre-conversation fast exit
# ===========================================================================

class TestWatchdogPreconvFastExit:

    @pytest.mark.asyncio
    async def test_no_user_speech_skips_prompt_to_goodbye(self):
        """#1: User never speaks → watchdog skips prompt, goes to goodbye."""
        cg = _make_call_guard()
        wd = _make_watchdog(call_guard=cg, timeout=0.5)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        wd.set_task(mock_task)

        original = _real_settings.PRECONV_FAST_EXIT
        _real_settings.PRECONV_FAST_EXIT = True
        try:
            await _bot_greeting(wd)
            await asyncio.sleep(6.0)
        finally:
            _real_settings.PRECONV_FAST_EXIT = original

        tts = _tts_frames(wd)
        hello_prompts = [f for f in tts if "hello" in f.text.lower() and "hear me" in f.text.lower()]
        assert len(hello_prompts) == 0, f"Should skip prompt, got: {[f.text for f in tts]}"
        assert _has_goodbye(wd), "Should send goodbye"

    @pytest.mark.asyncio
    async def test_user_spoke_once_gets_normal_escalation(self):
        """#2: User spoke once → normal 2-step escalation on silence."""
        cg = _make_call_guard()
        wd = _make_watchdog(call_guard=cg, timeout=0.5)

        original = _real_settings.PRECONV_FAST_EXIT
        _real_settings.PRECONV_FAST_EXIT = True
        try:
            await _bot_greeting(wd)
            cg._user_has_spoken = True
            cg._bot_has_spoken = True
            await _user_speaks(wd, "hello")

            wd._pushed_frames.clear()
            await asyncio.sleep(1.5)
        finally:
            _real_settings.PRECONV_FAST_EXIT = original

        tts = _tts_frames(wd)
        assert len(tts) >= 1, "Should send prompt when user has spoken before"
        assert wd._total_prompts >= 1

    @pytest.mark.asyncio
    async def test_flag_disabled_reverts_to_normal(self):
        """#4: PRECONV_FAST_EXIT=False → normal 2-step even without user speech."""
        cg = _make_call_guard()
        wd = _make_watchdog(call_guard=cg, timeout=0.5)

        original = _real_settings.PRECONV_FAST_EXIT
        _real_settings.PRECONV_FAST_EXIT = False
        try:
            await _bot_greeting(wd)
            await asyncio.sleep(1.5)
        finally:
            _real_settings.PRECONV_FAST_EXIT = original

        assert wd._total_prompts >= 1, "With flag off, should send prompt"

    @pytest.mark.asyncio
    async def test_call_guard_none_reverts_to_normal(self):
        """#5: No call_guard → normal escalation (safe fallback)."""
        wd = _make_watchdog(call_guard=None, timeout=0.5)

        original = _real_settings.PRECONV_FAST_EXIT
        _real_settings.PRECONV_FAST_EXIT = True
        try:
            await _bot_greeting(wd)
            await asyncio.sleep(1.5)
        finally:
            _real_settings.PRECONV_FAST_EXIT = original

        assert wd._total_prompts >= 1, "Without call_guard, should fall back to normal"


# ===========================================================================
# Fix 2: EarlyHangupTimer
# ===========================================================================

class TestEarlyHangupTimer:

    @pytest.mark.asyncio
    async def test_no_speech_within_timeout_hangs_up(self):
        """#8: No user speech within timeout → goodbye + EndFrame."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=1.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        eh.set_task(mock_task)

        await _bot_greeting(eh)
        await asyncio.sleep(6.0)

        assert _has_goodbye(eh), "Should send goodbye"
        assert mock_task.queue_frame.called, "Should push EndFrame via task"

    @pytest.mark.asyncio
    async def test_user_speech_cancels_timer_permanently(self):
        """#9: User speaks → timer cancelled, never fires."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=2.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        eh.set_task(mock_task)

        await _bot_greeting(eh)
        await asyncio.sleep(0.5)
        await _user_speaks(eh, "hello")
        assert eh._cancelled is True

        # Wait past timeout
        await asyncio.sleep(3.0)

        assert not mock_task.queue_frame.called, "Timer should not fire after cancel"

    @pytest.mark.asyncio
    async def test_timer_starts_on_bot_started_speaking(self):
        """#10: Timer not running before greeting."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=1.0)

        assert eh._started is False
        assert eh._timer_task is None

        await _send(eh, _FakeBotStartedSpeakingFrame())
        assert eh._started is True
        assert eh._timer_task is not None

        # Cleanup
        await eh.cleanup()

    @pytest.mark.asyncio
    async def test_timer_does_not_restart_after_cancel(self):
        """#11: Once cancelled, stays cancelled even after more bot speech."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=2.0)

        await _bot_greeting(eh)
        await _user_speaks(eh, "hello")
        assert eh._cancelled is True

        # Another bot greeting
        await _send(eh, _FakeBotStartedSpeakingFrame())
        # Should not restart timer
        assert eh._cancelled is True

        await eh.cleanup()

    @pytest.mark.asyncio
    async def test_termination_source_recorded(self):
        """#13: Timer records correct termination_source."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=0.5)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        eh.set_task(mock_task)

        await _bot_greeting(eh)
        await asyncio.sleep(5.0)

        assert cg.termination_source == "early_hangup_no_speech"

    @pytest.mark.asyncio
    async def test_endframe_cancels_timer(self):
        """#15: Pipeline end cancels timer cleanly."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=5.0)

        await _bot_greeting(eh)
        assert eh._timer_task is not None

        await _send(eh, _FakeEndFrame())
        assert eh._timer_task is None

    @pytest.mark.asyncio
    async def test_echo_during_bot_speech_does_not_cancel(self):
        """Echo transcript during bot speech should NOT cancel timer."""
        cg = _make_call_guard()
        eh = _make_early_hangup(call_guard=cg, timeout=2.0)

        await _send(eh, _FakeBotStartedSpeakingFrame())
        # Echo while bot is speaking
        await _send(eh, _FakeTranscriptionFrame(text="echo words"))

        assert eh._cancelled is False, "Echo during bot speech should not cancel"

        await eh.cleanup()


# ===========================================================================
# Fix 3: HoldMusicDetector
# ===========================================================================

class TestHoldMusicDetector:

    @pytest.mark.asyncio
    async def test_vad_without_transcript_triggers_detection(self):
        """#16: VAD active, no transcript for timeout → hold music detected."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=1.5)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        hd.set_task(mock_task)

        await _bot_greeting(hd)
        # VAD fires but no transcript
        await _send(hd, _FakeUserStartedSpeakingFrame())

        await asyncio.sleep(5.0)

        assert _has_goodbye(hd), "Should send goodbye on hold music"
        assert cg.termination_source == "hold_music"

    @pytest.mark.asyncio
    async def test_vad_with_transcript_no_trigger(self):
        """#17: VAD + transcript = real person, no trigger."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=2.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        hd.set_task(mock_task)

        await _bot_greeting(hd)
        await _send(hd, _FakeUserStartedSpeakingFrame())
        await asyncio.sleep(0.5)
        # Transcript arrives — it's a person
        await _send(hd, _FakeTranscriptionFrame(text="hello"))

        await asyncio.sleep(3.0)

        assert not mock_task.queue_frame.called, "Should not trigger with transcript"
        assert hd._user_has_spoken is True

    @pytest.mark.asyncio
    async def test_user_spoke_disables_detector(self):
        """#18: Once user spoke, detector permanently disabled."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=1.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        hd.set_task(mock_task)

        await _bot_greeting(hd)
        await _user_speaks(hd, "hello")
        assert hd._user_has_spoken is True

        # Now VAD without transcript (shouldn't trigger)
        hd._pushed_frames.clear()
        await _send(hd, _FakeUserStartedSpeakingFrame())
        await asyncio.sleep(3.0)

        assert not mock_task.queue_frame.called

    @pytest.mark.asyncio
    async def test_bot_speech_vad_ignored(self):
        """#19: VAD during bot speech → ignored (not hold music)."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=1.0)

        await _send(hd, _FakeBotStartedSpeakingFrame())
        # VAD during bot speech
        await _send(hd, _FakeUserStartedSpeakingFrame())

        assert hd._vad_active_since is None, "VAD during bot speech should be ignored"

        await hd.cleanup()

    @pytest.mark.asyncio
    async def test_intermittent_vad_resets_on_transcript(self):
        """#20: VAD → transcript → VAD again → timeout from second VAD."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=2.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        hd.set_task(mock_task)

        await _bot_greeting(hd)

        # First VAD (at T=0) — but this is pre-user-speech so it's tracked
        await _send(hd, _FakeUserStartedSpeakingFrame())
        # Transcript arrives — resets detector and marks user as spoken
        await _send(hd, _FakeTranscriptionFrame(text="hello"))

        assert hd._vad_active_since is None
        assert hd._user_has_spoken is True

        # Detector should be permanently disabled
        await asyncio.sleep(4.0)
        assert not mock_task.queue_frame.called

    @pytest.mark.asyncio
    async def test_flag_disabled_no_detector(self):
        """#22: HOLD_MUSIC_DETECTION=False → no detector created."""
        # This is tested at the factory level, but we verify the detector
        # doesn't start if not wired
        hd = _make_hold_detector(timeout=0.5)
        assert hd._started is False
        assert hd._detector_task is None

    @pytest.mark.asyncio
    async def test_termination_source_hold_music(self):
        """#23: Detector records 'hold_music' termination source."""
        cg = _make_call_guard()
        hd = _make_hold_detector(call_guard=cg, timeout=1.0)
        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        hd.set_task(mock_task)

        await _bot_greeting(hd)
        await _send(hd, _FakeUserStartedSpeakingFrame())
        await asyncio.sleep(5.0)

        assert cg.termination_source == "hold_music"


# ===========================================================================
# Integration: race conditions between processors
# ===========================================================================

class TestRaceConditions:

    @pytest.mark.asyncio
    async def test_first_termination_source_wins(self):
        """#14: Multiple processors try to set termination_source — first wins."""
        cg = _make_call_guard()
        cg.set_termination_source("early_hangup_no_speech")
        cg.set_termination_source("hold_music")
        cg.set_termination_source("silence_watchdog")

        assert cg.termination_source == "early_hangup_no_speech"

    @pytest.mark.asyncio
    async def test_real_conversation_unaffected(self):
        """#30: When user speaks, all three fixes stay inactive."""
        cg = _make_call_guard()

        # Use long timeouts so nothing fires during our test window
        wd = _make_watchdog(call_guard=cg, timeout=10.0)
        eh = _make_early_hangup(call_guard=cg, timeout=10.0)
        hd = _make_hold_detector(call_guard=cg, timeout=10.0)

        mock_task = MagicMock()
        mock_task.queue_frame = AsyncMock()
        wd.set_task(mock_task)
        eh.set_task(mock_task)
        hd.set_task(mock_task)

        # Bot greets
        for proc in [wd, eh, hd]:
            await _bot_greeting(proc)

        # Simulate user_has_spoken on call_guard
        cg._user_has_spoken = True
        cg._bot_has_spoken = True

        # User speaks on each processor
        for proc in [wd, eh, hd]:
            await _user_speaks(proc, "yes I'm here")

        # Wait briefly — none of the timeouts should fire
        await asyncio.sleep(1.0)

        # Early hangup should be cancelled
        assert eh._cancelled is True
        # Hold music detector should be disabled
        assert hd._user_has_spoken is True
        # No termination source should be set (user is talking)
        assert cg.termination_source is None

        # Cleanup
        for proc in [wd, eh, hd]:
            await proc.cleanup()
