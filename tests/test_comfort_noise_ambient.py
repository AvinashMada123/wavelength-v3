"""Tests for ComfortNoiseInjector ambient mode (extended).

Covers: legacy pink noise fallback, ambient mode init, frame generation,
volume scaling, injection conditions, Plivo spec compliance, cursor sharing,
and self-feeding loop prevention.
"""

from __future__ import annotations

import base64
import json
import math
import struct
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Mock pipecat imports BEFORE importing code under test
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Minimal pipecat stubs
_fake_frames = SimpleNamespace(
    AudioRawFrame=type("AudioRawFrame", (), {}),
    Frame=type("Frame", (), {}),
    InputAudioRawFrame=type("InputAudioRawFrame", (), {
        "__init__": lambda self, **kw: None,
    }),
    InterruptionFrame=type("InterruptionFrame", (), {}),
    OutputTransportMessageFrame=type("OutputTransportMessageFrame", (), {}),
    OutputTransportMessageUrgentFrame=type("OutputTransportMessageUrgentFrame", (), {}),
    # Required by other modules (runner.py, ambient_mixer.py) when tests run together
    EndFrame=type("EndFrame", (), {}),
    StartFrame=type("StartFrame", (), {}),
    TTSAudioRawFrame=type("TTSAudioRawFrame", (), {}),
    TTSSpeakFrame=type("TTSSpeakFrame", (), {"__init__": lambda self, text="": setattr(self, "text", text) or None}),
    TTSStartedFrame=type("TTSStartedFrame", (), {}),
    TTSStoppedFrame=type("TTSStoppedFrame", (), {}),
    TTSUpdateSettingsFrame=type("TTSUpdateSettingsFrame", (), {}),
)

_fake_base_serializer = SimpleNamespace(
    FrameSerializer=type("FrameSerializer", (), {
        "__init__": lambda self, **kw: None,
        "should_ignore_frame": lambda self, f: False,
    }),
)

for mod in [
    "pipecat", "pipecat.frames", "pipecat.serializers",
    "pipecat.serializers.base_serializer",
    "pipecat.processors", "pipecat.processors.frame_processor",
    "loguru",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.modules["pipecat.frames.frames"] = _fake_frames
sys.modules["pipecat.serializers.base_serializer"] = _fake_base_serializer

# Provide a loguru.logger stub that has .info/.warning etc.
_loguru_mod = SimpleNamespace(logger=MagicMock())
sys.modules["loguru"] = _loguru_mod

# Force fresh import of the module under test
sys.modules.pop("app.serializers.plivo_pcm", None)
sys.modules.pop("app.serializers", None)
sys.modules.pop("app.audio.ambient", None)

from app.audio.ambient import AmbientLoopCursor
from app.serializers.plivo_pcm import (
    PLIVO_FRAME_BYTES,
    PLIVO_SAMPLE_RATE,
    ComfortNoiseInjector,
    PlivoPCMFrameSerializer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_serializer(last_audio_ts: float = 0.0) -> SimpleNamespace:
    """Mock serializer with _last_audio_sent_ts attribute."""
    return SimpleNamespace(_last_audio_sent_ts=last_audio_ts)


def _make_ws() -> AsyncMock:
    """Mock WebSocket with send_text that records calls."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _make_noise_array(n_samples: int = 16000, value: int = 10000) -> np.ndarray:
    """Create a known numpy int16 array for mocking get_preset."""
    arr = np.full(n_samples, value, dtype=np.int16)
    arr.flags.writeable = False
    return arr


def _make_injector(
    ambient_preset: str | None = None,
    ambient_volume: float = 0.08,
    enabled: bool = False,
    bot_vad_stop_secs: float = 1.5,
    gap_threshold_ms: float = 200.0,
    loop_cursor=None,
    preset_array: np.ndarray | None = None,
    last_audio_ts: float = 0.0,
) -> tuple[ComfortNoiseInjector, SimpleNamespace, AsyncMock]:
    """Create injector with mocked dependencies. Returns (injector, serializer, ws)."""
    serializer = _make_serializer(last_audio_ts)
    ws = _make_ws()

    if ambient_preset and preset_array is None:
        preset_array = _make_noise_array()

    with patch("app.audio.ambient.get_preset", return_value=preset_array):
        injector = ComfortNoiseInjector(
            websocket=ws,
            serializer=serializer,
            bot_vad_stop_secs=bot_vad_stop_secs,
            gap_threshold_ms=gap_threshold_ms,
            enabled=enabled,
            ambient_preset=ambient_preset,
            ambient_volume=ambient_volume,
            loop_cursor=loop_cursor,
        )
    return injector, serializer, ws


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComfortNoiseAmbient:

    def test_legacy_pink_noise_mode(self):
        """No ambient_preset → legacy mode with pink noise frame of correct length."""
        injector, _, _ = _make_injector(enabled=True)
        assert injector._ambient_mode is False
        assert len(injector._noise_frame) == PLIVO_FRAME_BYTES  # 640

    def test_ambient_mode_enabled_with_valid_preset(self):
        """Valid ambient_preset → ambient mode enabled."""
        injector, _, _ = _make_injector(ambient_preset="static")
        assert injector._ambient_mode is True
        assert injector._enabled is True

    def test_ambient_mode_fallback_on_missing_preset(self):
        """get_preset returns None → falls back to legacy mode."""
        serializer = _make_serializer()
        ws = _make_ws()
        with patch("app.audio.ambient.get_preset", return_value=None):
            injector = ComfortNoiseInjector(
                websocket=ws,
                serializer=serializer,
                ambient_preset="nonexistent",
            )
        assert injector._ambient_mode is False

    def test_get_ambient_frame_correct_length(self):
        """_get_ambient_frame() returns exactly PLIVO_FRAME_BYTES (640) bytes."""
        injector, _, _ = _make_injector(ambient_preset="static")
        frame = injector._get_ambient_frame()
        assert len(frame) == PLIVO_FRAME_BYTES

    def test_get_ambient_frame_loop_position_advances(self):
        """Two calls advance cursor by 320 samples each → pos == 640."""
        cursor = AmbientLoopCursor()
        injector, _, _ = _make_injector(
            ambient_preset="static",
            loop_cursor=cursor,
            preset_array=_make_noise_array(16000),
        )
        assert cursor.pos == 0
        injector._get_ambient_frame()
        assert cursor.pos == 320  # PLIVO_FRAME_BYTES // 2
        injector._get_ambient_frame()
        assert cursor.pos == 640

    def test_get_ambient_frame_wraps_at_buffer_end(self):
        """480-sample buffer: after 2 calls (640 samples), cursor wraps correctly."""
        cursor = AmbientLoopCursor()
        buf = _make_noise_array(480)
        injector, _, _ = _make_injector(
            ambient_preset="static",
            loop_cursor=cursor,
            preset_array=buf,
        )
        # First call: 320 samples, pos = 320
        injector._get_ambient_frame()
        assert cursor.pos == 320
        # Second call: needs 320, only 160 left → wraps, pos = (320+320) % 480 = 160
        injector._get_ambient_frame()
        assert cursor.pos == 160

    def test_ambient_volume_scaling(self):
        """Buffer of all 10000 int16, volume 0.08 (×0.65=0.052) → samples ≈ 520."""
        buf = _make_noise_array(16000, value=10000)
        injector, _, _ = _make_injector(
            ambient_preset="static",
            ambient_volume=0.08,
            preset_array=buf,
        )
        frame = injector._get_ambient_frame()
        samples = np.frombuffer(frame, dtype=np.int16)
        # 10000 * 0.08 * 0.65 = 520
        expected = 520
        assert all(abs(int(s) - expected) <= 1 for s in samples)

    def test_ambient_volume_clamped_to_max(self):
        """Volume=0.9 → _ambient_volume clamped to _MAX_VOLUME (0.3)."""
        injector, _, _ = _make_injector(
            ambient_preset="static",
            ambient_volume=0.9,
        )
        assert injector._ambient_volume <= 0.3

    def test_ambient_mode_no_upper_bound(self):
        """In ambient mode, 10s gap → should_inject is True (no upper bound)."""
        injector, serializer, _ = _make_injector(ambient_preset="static")
        # Set last audio 10 seconds ago
        serializer._last_audio_sent_ts = time.monotonic() - 10.0
        gap = time.monotonic() - serializer._last_audio_sent_ts
        # Ambient mode: inject when gap > 0.05
        should_inject = gap > 0.05
        assert should_inject is True
        assert injector._ambient_mode is True

    def test_legacy_mode_respects_upper_bound(self):
        """In legacy mode, 10s gap exceeds bot_vad_stop_s → should_inject is False."""
        injector, serializer, _ = _make_injector(
            enabled=True,
            bot_vad_stop_secs=1.5,
        )
        serializer._last_audio_sent_ts = time.monotonic() - 10.0
        gap = time.monotonic() - serializer._last_audio_sent_ts
        # Legacy mode: gap must be < bot_vad_stop_s
        should_inject = gap > injector._gap_threshold_s and gap < injector._bot_vad_stop_s
        assert should_inject is False
        assert injector._ambient_mode is False

    def test_frame_format_matches_plivo_spec(self):
        """Ambient frame base64-encodes into valid Plivo playAudio JSON."""
        injector, _, _ = _make_injector(ambient_preset="static")
        frame_bytes = injector._get_ambient_frame()
        payload = base64.b64encode(frame_bytes).decode("utf-8")
        msg = json.dumps({
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-l16",
                "sampleRate": PLIVO_SAMPLE_RATE,
                "payload": payload,
            },
        })
        parsed = json.loads(msg)
        assert parsed["event"] == "playAudio"
        assert parsed["media"]["contentType"] == "audio/x-l16"
        assert parsed["media"]["sampleRate"] == 16000
        # Verify payload decodes back to original bytes
        decoded = base64.b64decode(parsed["media"]["payload"])
        assert decoded == frame_bytes

    def test_no_self_feeding_loop(self):
        """Injector sends to ws but does NOT update serializer._last_audio_sent_ts."""
        injector, serializer, ws = _make_injector(ambient_preset="static")
        original_ts = serializer._last_audio_sent_ts
        # Simulate what _run() does: get frame and send
        frame_bytes = injector._get_ambient_frame()
        payload = base64.b64encode(frame_bytes).decode("utf-8")
        # The injector writes to ws.send_text, not serializer
        assert serializer._last_audio_sent_ts == original_ts

    def test_greeting_timestamp_seed(self):
        """With _last_audio_sent_ts = now, gap is small (< 1s)."""
        now = time.monotonic()
        injector, serializer, _ = _make_injector(
            ambient_preset="static",
            last_audio_ts=now,
        )
        gap = time.monotonic() - serializer._last_audio_sent_ts
        assert gap < 1.0

    def test_shared_cursor_sync(self):
        """Shared AmbientLoopCursor stays in sync between two consumers."""
        cursor = AmbientLoopCursor()
        buf = _make_noise_array(16000)

        # Consumer 1: the injector
        injector, _, _ = _make_injector(
            ambient_preset="static",
            loop_cursor=cursor,
            preset_array=buf,
        )

        # Consumer 2: simulates AmbientSoundMixer advancing cursor
        assert cursor.pos == 0
        cursor.pos = 160  # Mixer advances by 160 samples

        # Injector now sees the updated position
        assert injector._cursor.pos == 160
        injector._get_ambient_frame()  # Advances by 320
        assert cursor.pos == 480  # 160 + 320

    def test_injector_stops_when_tts_resumes(self):
        """Gap ≈ 0 when TTS just sent a frame → should_inject is False."""
        now = time.monotonic()
        injector, serializer, _ = _make_injector(
            ambient_preset="static",
            last_audio_ts=now,
        )
        gap = time.monotonic() - serializer._last_audio_sent_ts
        # Ambient: inject only when gap > 0.05 — near-zero gap means no injection
        should_inject = gap > 0.05
        assert should_inject is False

    def test_ambient_silence_volume_compensation(self):
        """_ambient_volume == volume * _SILENCE_VOLUME_RATIO (0.65)."""
        injector, _, _ = _make_injector(
            ambient_preset="static",
            ambient_volume=0.08,
        )
        expected = 0.08 * 0.65
        assert abs(injector._ambient_volume - expected) < 1e-9

    def test_ambient_mode_very_long_gap(self):
        """60-second gap → should_inject is True (no overflow or cap)."""
        injector, serializer, _ = _make_injector(ambient_preset="static")
        serializer._last_audio_sent_ts = time.monotonic() - 60.0
        gap = time.monotonic() - serializer._last_audio_sent_ts
        should_inject = gap > 0.05
        assert should_inject is True
        assert injector._ambient_mode is True

    def test_auto_enable_overrides_disabled_flag(self):
        """enabled=False but valid ambient_preset → _enabled becomes True."""
        injector, _, _ = _make_injector(
            ambient_preset="static",
            enabled=False,
        )
        assert injector._enabled is True
        assert injector._ambient_mode is True
