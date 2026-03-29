"""Tests for ambient sound WAV loader and AmbientSoundMixer processor.

Covers: WAV validation/loading, mixer init, frame processing, audio mixing
correctness, and integration behavior (greeting mix function).
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports BEFORE importing code under test
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


class _FakeFrame:
    pass


class _FakeStartFrame(_FakeFrame):
    pass


class _FakeEndFrame(_FakeFrame):
    pass


class _FakeTTSAudioRawFrame(_FakeFrame):
    def __init__(self, audio: bytes = b"", sample_rate: int = 16000, num_channels: int = 1):
        self.audio = audio
        self.sample_rate = sample_rate
        self.num_channels = num_channels


_frames_mod = SimpleNamespace(
    EndFrame=_FakeEndFrame,
    StartFrame=_FakeStartFrame,
    TTSAudioRawFrame=_FakeTTSAudioRawFrame,
    Frame=_FakeFrame,
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

# Force fresh imports with our stubs
sys.modules.pop("app.pipeline.ambient_mixer", None)
sys.modules.pop("app.audio.ambient", None)
sys.modules.pop("app.pipeline.runner", None)

from app.audio.ambient import (
    EXPECTED_CHANNELS,
    EXPECTED_SAMPLE_RATE,
    EXPECTED_SAMPLE_WIDTH,
    _reset_for_testing,
    _validate_and_load,
    get_preset,
    load_presets,
)
from app.pipeline.ambient_mixer import MAX_VOLUME, AmbientSoundMixer

DOWNSTREAM = "downstream"


# ---------------------------------------------------------------------------
# WAV Fixture Helper
# ---------------------------------------------------------------------------

def _make_wav(
    tmp_path: Path,
    name: str = "test.wav",
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
    n_samples: int = 16000,
) -> Path:
    path = tmp_path / name
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        samples = [int(16000 * math.sin(2 * math.pi * 100 * i / sample_rate)) for i in range(n_samples)]
        if sample_width == 1:
            # 8-bit unsigned
            wf.writeframes(struct.pack(f"<{len(samples)}B", *[max(0, min(255, s + 128)) for s in samples]))
        else:
            wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    path.write_bytes(buf.getvalue())
    return path


def _make_noise_array(n_samples: int = 16000) -> np.ndarray:
    """Create a known noise numpy array for mocking get_preset."""
    arr = np.array(
        [int(1000 * math.sin(2 * math.pi * 200 * i / 16000)) for i in range(n_samples)],
        dtype=np.int16,
    )
    arr.flags.writeable = False
    return arr


def _make_mixer(preset: str = "static", volume: float = 0.08, call_sid: str = "test",
                noise_samples: int = 16000) -> AmbientSoundMixer:
    """Create a mixer with a buffer directly injected (bypasses get_preset)."""
    with patch("app.pipeline.ambient_mixer.get_preset", return_value=None):
        mixer = AmbientSoundMixer(preset=preset, volume=volume, call_sid=call_sid)
    mixer._buffer = _make_noise_array(noise_samples)
    mixer._active = True
    return mixer


def _pcm_bytes(n_samples: int = 160, amplitude: int = 5000) -> bytes:
    """Generate PCM bytes (16-bit LE) with a sine wave."""
    samples = [int(amplitude * math.sin(2 * math.pi * 400 * i / 16000)) for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *samples)


# ---------------------------------------------------------------------------
# A. WAV Loader Tests
# ---------------------------------------------------------------------------

class TestWavLoader:

    def setup_method(self):
        _reset_for_testing()

    def test_load_valid_wav(self, tmp_path):
        """Valid 16kHz mono 16-bit WAV loads as numpy int16 array."""
        path = _make_wav(tmp_path, n_samples=800)
        result = _validate_and_load(path, None)
        assert result is not None
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        assert len(result) == 800

    def test_load_wrong_sample_rate(self, tmp_path):
        """44.1kHz WAV is rejected (returns None)."""
        path = _make_wav(tmp_path, sample_rate=44100)
        result = _validate_and_load(path, None)
        assert result is None

    def test_load_wrong_channels(self, tmp_path):
        """Stereo WAV is rejected (returns None)."""
        path = _make_wav(tmp_path, channels=2, n_samples=800)
        result = _validate_and_load(path, None)
        assert result is None

    def test_load_wrong_bit_depth(self, tmp_path):
        """8-bit WAV is rejected (returns None)."""
        path = _make_wav(tmp_path, sample_width=1, n_samples=800)
        result = _validate_and_load(path, None)
        assert result is None

    def test_load_missing_file(self, tmp_path):
        """Nonexistent path returns None without crashing."""
        path = tmp_path / "nonexistent.wav"
        result = _validate_and_load(path, None)
        assert result is None

    def test_checksum_mismatch(self, tmp_path):
        """Valid WAV with wrong checksum returns None."""
        path = _make_wav(tmp_path, n_samples=800)
        result = _validate_and_load(path, "0000000000000000000000000000000000000000000000000000000000000000")
        assert result is None

    def test_get_preset_unknown(self):
        """get_preset for nonexistent name returns None."""
        assert get_preset("nonexistent") is None


# ---------------------------------------------------------------------------
# B. Mixer Init Tests
# ---------------------------------------------------------------------------

class TestMixerInit:

    def test_mixer_init_valid_preset(self):
        mixer = _make_mixer()
        assert mixer._active is True
        assert mixer._frames_mixed == 0

    def test_mixer_init_unknown_preset(self):
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=None):
            mixer = AmbientSoundMixer(preset="nonexistent", call_sid="test")
        assert mixer._active is False

    def test_mixer_volume_clamped_to_max(self):
        mixer = _make_mixer(volume=0.5)
        assert mixer._volume == MAX_VOLUME  # 0.3

    def test_mixer_volume_clamped_to_zero(self):
        mixer = _make_mixer(volume=-0.1)
        assert mixer._volume == 0.0

    def test_mixer_default_volume(self):
        mixer = _make_mixer()
        assert mixer._volume == 0.08


# ---------------------------------------------------------------------------
# C. Frame Processing Tests
# ---------------------------------------------------------------------------

class TestFrameProcessing:

    @pytest.mark.asyncio
    async def test_tts_frame_mixed(self):
        """TTS frame audio is mixed (output differs from input)."""
        mixer = _make_mixer(volume=0.1)
        original_audio = _pcm_bytes(160)
        frame = _FakeTTSAudioRawFrame(audio=original_audio, sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert len(mixer._pushed_frames) == 1
        # frame.audio was modified in-place by the mixer
        assert mixer._pushed_frames[0].audio != original_audio

    @patch("app.pipeline.ambient_mixer.get_preset")
    @pytest.mark.asyncio
    async def test_tts_frame_preserves_sample_rate(self, mock_get):
        mock_get.return_value = _make_noise_array()
        mixer = AmbientSoundMixer(preset="static", call_sid="test")
        frame = _FakeTTSAudioRawFrame(audio=_pcm_bytes(160), sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert mixer._pushed_frames[0].sample_rate == 16000

    @patch("app.pipeline.ambient_mixer.get_preset")
    @pytest.mark.asyncio
    async def test_tts_frame_preserves_num_channels(self, mock_get):
        mock_get.return_value = _make_noise_array()
        mixer = AmbientSoundMixer(preset="static", call_sid="test")
        frame = _FakeTTSAudioRawFrame(audio=_pcm_bytes(160), sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert mixer._pushed_frames[0].num_channels == 1

    @pytest.mark.asyncio
    async def test_non_tts_frame_passthrough(self):
        """Non-TTS frames are passed through unchanged."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=_make_noise_array()):
            mixer = AmbientSoundMixer(preset="static", call_sid="test")
        frame = _FakeFrame()
        await mixer.process_frame(frame, DOWNSTREAM)
        assert len(mixer._pushed_frames) == 1
        assert mixer._pushed_frames[0] is frame

    @pytest.mark.asyncio
    async def test_start_frame_passthrough(self):
        """StartFrame is passed through unchanged."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=_make_noise_array()):
            mixer = AmbientSoundMixer(preset="static", call_sid="test")
        frame = _FakeStartFrame()
        await mixer.process_frame(frame, DOWNSTREAM)
        assert len(mixer._pushed_frames) == 1
        assert mixer._pushed_frames[0] is frame

    @pytest.mark.asyncio
    async def test_end_frame_passthrough(self):
        """EndFrame is passed through + summary logged."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=_make_noise_array()):
            mixer = AmbientSoundMixer(preset="static", call_sid="test")
        mixer._frames_mixed = 5
        frame = _FakeEndFrame()
        await mixer.process_frame(frame, DOWNSTREAM)
        assert len(mixer._pushed_frames) == 1
        assert mixer._pushed_frames[0] is frame

    @pytest.mark.asyncio
    async def test_inactive_mixer_passthrough(self):
        """When _active=False, TTS frames pass through unchanged."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=None):
            mixer = AmbientSoundMixer(preset="nonexistent", call_sid="test")
        assert mixer._active is False
        original_audio = _pcm_bytes(160)
        frame = _FakeTTSAudioRawFrame(audio=original_audio, sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert mixer._pushed_frames[0].audio == original_audio

    @pytest.mark.asyncio
    async def test_empty_audio_passthrough(self):
        """Frame with empty audio bytes passes through."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=_make_noise_array()):
            mixer = AmbientSoundMixer(preset="static", call_sid="test")
        frame = _FakeTTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert mixer._pushed_frames[0].audio == b""

    @pytest.mark.asyncio
    async def test_process_frame_exception_pushes_original(self):
        """Corrupt audio still gets pushed (exception caught)."""
        with patch("app.pipeline.ambient_mixer.get_preset", return_value=_make_noise_array()):
            mixer = AmbientSoundMixer(preset="static", call_sid="test")
        # Odd-length bytes can't be decoded as int16
        bad_audio = b"\x00\x01\x02"
        frame = _FakeTTSAudioRawFrame(audio=bad_audio, sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame, DOWNSTREAM)
        assert len(mixer._pushed_frames) == 1
        # Frame should still be pushed (original audio since _mix raised)
        assert mixer._pushed_frames[0] is frame

    @pytest.mark.asyncio
    async def test_multiple_frames_advance_loop_pos(self):
        """Processing multiple frames advances the loop position."""
        mixer = _make_mixer(noise_samples=1600)
        assert mixer._loop_pos == 0
        frame1 = _FakeTTSAudioRawFrame(audio=_pcm_bytes(160), sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame1, DOWNSTREAM)
        assert mixer._loop_pos == 160

        frame2 = _FakeTTSAudioRawFrame(audio=_pcm_bytes(160), sample_rate=16000, num_channels=1)
        await mixer.process_frame(frame2, DOWNSTREAM)
        assert mixer._loop_pos == 320


# ---------------------------------------------------------------------------
# D. Audio Mixing Correctness
# ---------------------------------------------------------------------------

class TestMixingCorrectness:

    def test_mix_adds_noise_to_speech(self):
        mixer = _make_mixer(volume=0.1, noise_samples=160)
        original = _pcm_bytes(160, amplitude=5000)
        mixed = mixer._mix(original)
        assert mixed != original

    def test_mix_volume_zero_unchanged(self):
        """Volume=0.0 produces identical output (noise scaled to zero)."""
        mixer = _make_mixer(volume=0.0, noise_samples=160)
        original = _pcm_bytes(160, amplitude=5000)
        mixed = mixer._mix(original)
        assert mixed == original

    def test_mix_clipping_protection(self):
        """Max amplitude speech + noise doesn't overflow int16 range."""
        mixer = _make_mixer(volume=MAX_VOLUME)
        # Override buffer with max-amplitude noise
        noise = np.full(16000, 32000, dtype=np.int16)
        noise.flags.writeable = False
        mixer._buffer = noise
        # Speech at near-max
        speech = struct.pack(f"<{160}h", *([32000] * 160))
        mixed = mixer._mix(speech)
        mixed_arr = np.frombuffer(mixed, dtype=np.int16)
        assert np.all(mixed_arr >= -32768)
        assert np.all(mixed_arr <= 32767)

    def test_loop_wraps_correctly(self):
        """Processing more samples than buffer length wraps the loop."""
        mixer = _make_mixer(volume=0.1, noise_samples=100)
        # Process 250 samples (wraps more than twice)
        pcm = _pcm_bytes(250, amplitude=3000)
        mixed = mixer._mix(pcm)
        assert len(mixed) == 500  # 250 samples * 2 bytes
        assert mixer._loop_pos == 250 % 100  # 50

    def test_concurrent_instances_independent(self):
        """Two mixer instances have independent loop positions."""
        mixer_a = _make_mixer(call_sid="call-a", noise_samples=1600)
        mixer_b = _make_mixer(call_sid="call-b", noise_samples=1600)

        mixer_a._mix(_pcm_bytes(160))
        assert mixer_a._loop_pos == 160
        assert mixer_b._loop_pos == 0

        mixer_b._mix(_pcm_bytes(80))
        assert mixer_b._loop_pos == 80
        assert mixer_a._loop_pos == 160


# ---------------------------------------------------------------------------
# E. Integration Behavior
# ---------------------------------------------------------------------------

class TestIntegrationBehavior:

    @pytest.mark.asyncio
    async def test_end_frame_logs_frame_count(self):
        """_frames_mixed == N after processing N TTS frames."""
        mixer = _make_mixer()
        for _ in range(7):
            frame = _FakeTTSAudioRawFrame(audio=_pcm_bytes(160), sample_rate=16000, num_channels=1)
            await mixer.process_frame(frame, DOWNSTREAM)
        assert mixer._frames_mixed == 7

    def test_volume_cap_constant(self):
        """MAX_VOLUME constant is 0.3."""
        assert MAX_VOLUME == 0.3

    @patch("app.audio.ambient.get_preset")
    def test_greeting_mix_function_valid(self, mock_get):
        """_mix_ambient_into_greeting produces valid PCM bytes."""
        # Mock all pipecat + app modules that runner imports at top-level
        _runner_extra_mods = [
            "pipecat.pipeline", "pipecat.pipeline.runner",
            "pipecat.transports", "pipecat.transports.services",
            "pipecat.transports.services.daily",
            "pipecat.services", "pipecat.services.google",
            "pipecat.services.deepgram",
            "plivo",
            "app.pipeline.factory", "app.serializers",
            "app.serializers.plivo_pcm",
        ]
        for mod_name in _runner_extra_mods:
            sys.modules.setdefault(mod_name, MagicMock())
        # Ensure TTSSpeakFrame exists in the frames mock
        if not hasattr(sys.modules["pipecat.frames.frames"], "TTSSpeakFrame"):
            sys.modules["pipecat.frames.frames"].TTSSpeakFrame = type(
                "TTSSpeakFrame", (_FakeFrame,), {"__init__": lambda self, text="": setattr(self, "text", text) or None}
            )

        sys.modules.pop("app.pipeline.runner", None)
        from app.pipeline.runner import _mix_ambient_into_greeting

        noise = _make_noise_array(320)
        mock_get.return_value = noise
        original = _pcm_bytes(160, amplitude=5000)
        result = _mix_ambient_into_greeting(original, "static", 0.1)
        assert isinstance(result, bytes)
        assert len(result) == len(original)
        assert result != original

    @patch("app.audio.ambient.get_preset")
    def test_greeting_mix_function_no_preset(self, mock_get):
        """Returns original bytes when preset is None/not loaded."""
        _runner_extra_mods = [
            "pipecat.pipeline", "pipecat.pipeline.runner",
            "pipecat.transports", "pipecat.transports.services",
            "pipecat.transports.services.daily",
            "pipecat.services", "pipecat.services.google",
            "pipecat.services.deepgram",
            "plivo",
            "app.pipeline.factory", "app.serializers",
            "app.serializers.plivo_pcm",
        ]
        for mod_name in _runner_extra_mods:
            sys.modules.setdefault(mod_name, MagicMock())
        if not hasattr(sys.modules["pipecat.frames.frames"], "TTSSpeakFrame"):
            sys.modules["pipecat.frames.frames"].TTSSpeakFrame = type(
                "TTSSpeakFrame", (_FakeFrame,), {"__init__": lambda self, text="": setattr(self, "text", text) or None}
            )

        sys.modules.pop("app.pipeline.runner", None)
        from app.pipeline.runner import _mix_ambient_into_greeting

        mock_get.return_value = None
        original = _pcm_bytes(160, amplitude=5000)
        result = _mix_ambient_into_greeting(original, "nonexistent", 0.08)
        assert result == original
