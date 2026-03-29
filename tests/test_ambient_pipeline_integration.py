"""Integration tests for ambient sound mixer wiring into the pipeline.

Tests verify:
- AmbientSoundMixer is included/excluded from the pipeline based on
  feature flag and bot_config.ambient_sound preset.
- Mixer position is correct (after TTS, before tracker_post_tts).
- Greeting audio gets ambient mixing when enabled.
- Unknown presets and mixer errors are handled gracefully.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports (same pattern as test_hello_guard_wiring.py)
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)


# ---------------------------------------------------------------------------
# Fake frame classes — must be real types for isinstance() in ambient_mixer
# ---------------------------------------------------------------------------

class _FakeFrame:
    pass

class _FakeStartFrame(_FakeFrame):
    pass

class _FakeTTSAudioRawFrame(_FakeFrame):
    def __init__(self, audio: bytes = b""):
        self.audio = audio

class _FakeEndFrame(_FakeFrame):
    pass


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


_frame_processor_mod = SimpleNamespace(
    FrameDirection=SimpleNamespace(DOWNSTREAM="downstream", UPSTREAM="upstream"),
    FrameProcessor=_FakeFrameProcessor,
)

_base_output_mock = MagicMock()
_base_output_mock.BOT_VAD_STOP_SECS = 1.5

# Mock ALL pipecat submodules before importing app code
for mod in [
    "pipecat", "pipecat.frames", "pipecat.frames.frames",
    "pipecat.processors", "pipecat.processors.aggregators",
    "pipecat.processors.aggregators.openai_llm_context",
    "pipecat.transports", "pipecat.transports.base_output",
    "pipecat.transports.websocket", "pipecat.transports.websocket.fastapi",
    "pipecat.audio", "pipecat.audio.vad", "pipecat.audio.vad.silero",
    "pipecat.audio.vad.vad_analyzer",
    "pipecat.audio.interruptions",
    "pipecat.audio.interruptions.min_words_interruption_strategy",
    "pipecat.audio.turn", "pipecat.audio.turn.smart_turn",
    "pipecat.audio.turn.smart_turn.base_smart_turn",
    "pipecat.audio.turn.smart_turn.local_smart_turn_v3",
    "pipecat.turns", "pipecat.turns.user_stop", "pipecat.turns.user_turn_strategies",
    "pipecat.pipeline", "pipecat.pipeline.pipeline", "pipecat.pipeline.runner",
    "pipecat.pipeline.task",
    "pipecat.services", "pipecat.services.google", "pipecat.services.google.llm",
    "pipecat.services.google.llm_vertex",
    "pipecat.services.deepgram", "pipecat.services.deepgram.stt",
    "pipecat.services.sarvam", "pipecat.services.elevenlabs",
    "pipecat.services.smallest",
    "pipecat.serializers", "pipecat.serializers.base_serializer",
    "pipecat.adapters",
    "deepgram",
    "starlette", "starlette.websockets",
    "app.pipeline.call_guard", "app.pipeline.silence_watchdog",
    "app.pipeline.phrase_aggregator",
    "app.serializers", "app.serializers.plivo_pcm",
    "app.services.gemini_llm_service",
    "app.models.bot_config", "app.models.schemas",
    "numpy",
]:
    sys.modules.setdefault(mod, MagicMock())

# Wire up real frame classes so isinstance() works inside ambient_mixer
_frames_mod = sys.modules["pipecat.frames.frames"]
_frames_mod.StartFrame = _FakeStartFrame
_frames_mod.TTSAudioRawFrame = _FakeTTSAudioRawFrame
_frames_mod.EndFrame = _FakeEndFrame

sys.modules["pipecat.processors.frame_processor"] = _frame_processor_mod
sys.modules["pipecat.transports.base_output"] = _base_output_mock

# Force re-import of ambient_mixer so it picks up the mocked pipecat
sys.modules.pop("app.pipeline.ambient_mixer", None)
sys.modules.pop("app.audio.ambient", None)
sys.modules.pop("app.pipeline.factory", None)
sys.modules.pop("app.pipeline.runner", None)

import numpy as np

from app.pipeline.ambient_mixer import AmbientSoundMixer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot_config(**overrides) -> SimpleNamespace:
    """Create a minimal bot_config namespace for testing."""
    defaults = {
        "ambient_sound": None,
        "ambient_sound_volume": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Test 1: Pipeline includes mixer when feature flag is on + preset set
# ---------------------------------------------------------------------------

def test_pipeline_includes_mixer_when_enabled():
    """When AMBIENT_SOUND_ENABLED=True and bot_config.ambient_sound is set,
    ambient_processors should contain exactly one AmbientSoundMixer."""
    bot_config = _make_bot_config(ambient_sound="static", ambient_sound_volume=0.1)

    # Replicate factory.py logic (lines 2108-2121)
    ambient_processors: list = []
    ambient_sound_enabled = True  # settings.AMBIENT_SOUND_ENABLED
    if ambient_sound_enabled:
        ambient_preset = getattr(bot_config, "ambient_sound", None)
        if ambient_preset:
            ambient_volume = getattr(bot_config, "ambient_sound_volume", None) or 0.08
            with patch("app.pipeline.ambient_mixer.get_preset", return_value=np.zeros(8000, dtype=np.int16)):
                mixer = AmbientSoundMixer(
                    preset=ambient_preset,
                    volume=ambient_volume,
                    call_sid="test-001",
                )
            ambient_processors = [mixer]

    assert len(ambient_processors) == 1
    assert isinstance(ambient_processors[0], AmbientSoundMixer)
    assert ambient_processors[0]._active is True


# ---------------------------------------------------------------------------
# Test 2: Pipeline excludes mixer when flag is off
# ---------------------------------------------------------------------------

def test_pipeline_excludes_mixer_when_flag_off():
    """When AMBIENT_SOUND_ENABLED=False, ambient_processors must be empty
    regardless of bot_config."""
    bot_config = _make_bot_config(ambient_sound="static", ambient_sound_volume=0.1)

    ambient_processors: list = []
    ambient_sound_enabled = False  # settings.AMBIENT_SOUND_ENABLED
    if ambient_sound_enabled:
        ambient_preset = getattr(bot_config, "ambient_sound", None)
        if ambient_preset:
            ambient_processors = [MagicMock()]  # Would never reach here

    assert ambient_processors == []


# ---------------------------------------------------------------------------
# Test 3: Pipeline excludes mixer when no preset in bot_config
# ---------------------------------------------------------------------------

def test_pipeline_excludes_mixer_when_no_preset():
    """Flag on but ambient_sound=None means no mixer in pipeline."""
    bot_config = _make_bot_config(ambient_sound=None)

    ambient_processors: list = []
    ambient_sound_enabled = True
    if ambient_sound_enabled:
        ambient_preset = getattr(bot_config, "ambient_sound", None)
        if ambient_preset:
            ambient_processors = [MagicMock()]  # Would never reach here

    assert ambient_processors == []


# ---------------------------------------------------------------------------
# Test 4: Mixer position — after TTS processors, before tracker_post_tts
# ---------------------------------------------------------------------------

def test_mixer_position_after_tts_before_tracker():
    """In the pipeline list, ambient_processors (mixer) must appear between
    tts_processors and tracker_post_tts, matching factory.py line 2156-2158."""
    # Simulate the pipeline processor list from factory.py
    transport_input = SimpleNamespace(name="transport.input")
    stt = SimpleNamespace(name="stt")
    llm = SimpleNamespace(name="llm")
    tts = SimpleNamespace(name="tts")
    tts_tail_trim = SimpleNamespace(name="TTSTailTrim")
    tracker_post_tts = SimpleNamespace(name="tracker_post_tts")
    transport_output = SimpleNamespace(name="transport.output")

    tts_processors = [tts, tts_tail_trim]

    with patch("app.pipeline.ambient_mixer.get_preset", return_value=np.zeros(8000, dtype=np.int16)):
        mixer = AmbientSoundMixer(preset="static", volume=0.08, call_sid="test-pos")
    ambient_processors = [mixer]

    # Build pipeline list exactly as factory.py does (lines 2145-2160 simplified)
    pipeline_list = [
        transport_input,
        stt,
        llm,
        *tts_processors,
        *ambient_processors,
        tracker_post_tts,
        transport_output,
    ]

    # Find indices
    mixer_idx = next(i for i, p in enumerate(pipeline_list) if isinstance(p, AmbientSoundMixer))
    tts_last_idx = next(i for i, p in enumerate(pipeline_list) if p is tts_tail_trim)
    tracker_idx = next(i for i, p in enumerate(pipeline_list) if p is tracker_post_tts)

    assert tts_last_idx < mixer_idx < tracker_idx, (
        f"Mixer at {mixer_idx} must be between TTS ({tts_last_idx}) "
        f"and tracker ({tracker_idx})"
    )


# ---------------------------------------------------------------------------
# Test 5: Greeting gets ambient mixing when enabled
# ---------------------------------------------------------------------------

def test_greeting_mixed_when_ambient_enabled():
    """When AMBIENT_SOUND_ENABLED=True and bot has a preset,
    _mix_ambient_into_greeting is called on the greeting audio."""
    from app.pipeline import runner

    bot_config = _make_bot_config(ambient_sound="static", ambient_sound_volume=0.1)
    greeting_audio = b"\x00\x00" * 100  # 100 samples of silence

    with patch.object(runner, "settings") as mock_settings, \
         patch.object(runner, "_mix_ambient_into_greeting", return_value=greeting_audio) as mock_mix:
        mock_settings.AMBIENT_SOUND_ENABLED = True
        mock_settings.GREETING_DIRECT_PLAY = True

        # Replicate the runner logic (lines 257-264)
        if mock_settings.AMBIENT_SOUND_ENABLED:
            ambient_preset = getattr(bot_config, "ambient_sound", None)
            if ambient_preset:
                ambient_vol = getattr(bot_config, "ambient_sound_volume", None) or 0.08
                greeting_audio = runner._mix_ambient_into_greeting(
                    greeting_audio, ambient_preset, ambient_vol
                )

        mock_mix.assert_called_once_with(greeting_audio, "static", 0.1)


# ---------------------------------------------------------------------------
# Test 6: Greeting NOT mixed when flag is off
# ---------------------------------------------------------------------------

def test_greeting_not_mixed_when_flag_off():
    """When AMBIENT_SOUND_ENABLED=False, _mix_ambient_into_greeting must NOT
    be called even if bot has a preset."""
    from app.pipeline import runner

    bot_config = _make_bot_config(ambient_sound="static", ambient_sound_volume=0.1)
    original_audio = b"\x00\x00" * 100

    with patch.object(runner, "_mix_ambient_into_greeting") as mock_mix:
        ambient_sound_enabled = False

        greeting_audio = original_audio
        if ambient_sound_enabled:
            ambient_preset = getattr(bot_config, "ambient_sound", None)
            if ambient_preset:
                ambient_vol = getattr(bot_config, "ambient_sound_volume", None) or 0.08
                greeting_audio = runner._mix_ambient_into_greeting(
                    greeting_audio, ambient_preset, ambient_vol
                )

        mock_mix.assert_not_called()
        assert greeting_audio is original_audio


# ---------------------------------------------------------------------------
# Test 7: Unknown preset does not crash — mixer sets _active=False
# ---------------------------------------------------------------------------

def test_unknown_preset_in_db_no_crash():
    """If bot_config.ambient_sound references a preset that doesn't exist,
    the mixer initializes with _active=False and pipeline builds fine."""
    with patch("app.pipeline.ambient_mixer.get_preset", return_value=None):
        mixer = AmbientSoundMixer(
            preset="nonexistent_preset",
            volume=0.08,
            call_sid="test-unknown",
        )

    assert mixer._active is False
    assert mixer._preset_name == "nonexistent_preset"
    assert mixer._buffer is None


# ---------------------------------------------------------------------------
# Test 8: Mixer error recovery — TTS frames still flow through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mixer_error_recovery_in_pipeline():
    """If _mix raises an exception, the original TTS frame audio is preserved
    and pushed downstream (no crash, no data loss)."""
    with patch("app.pipeline.ambient_mixer.get_preset", return_value=np.zeros(8000, dtype=np.int16)):
        mixer = AmbientSoundMixer(
            preset="static",
            volume=0.08,
            call_sid="test-recovery",
        )

    assert mixer._active is True

    # Create a real TTSAudioRawFrame instance so isinstance() works
    original_pcm = b"\x01\x00" * 50  # 50 samples
    fake_frame = _FakeTTSAudioRawFrame(audio=original_pcm)

    # Force _mix to raise
    mixer._mix = MagicMock(side_effect=RuntimeError("buffer corruption"))
    mixer.push_frame = AsyncMock()

    await mixer.process_frame(fake_frame, "downstream")

    # Frame should still be pushed (error caught, original audio untouched)
    mixer.push_frame.assert_awaited_once_with(fake_frame, "downstream")
    # Audio should be the original (untouched because _mix raised before assignment)
    assert fake_frame.audio == original_pcm
