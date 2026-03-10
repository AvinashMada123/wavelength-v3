"""
Stateless Plivo PCM 16kHz frame serializer.

Plivo bidirectional streams use raw PCM 16-bit signed LE at 16kHz
(contentType="audio/x-l16;rate=16000"). No mulaw conversion needed.

Recording is handled server-side by Plivo's Record XML element.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import time
from collections import deque

from loguru import logger

from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

PLIVO_SAMPLE_RATE = 16000
# 20ms frame at 16kHz, 16-bit mono = 640 bytes
PLIVO_FRAME_BYTES = int(PLIVO_SAMPLE_RATE * 2 * 0.02)

# --- Echo RTT measurement (Phase 0) ---
# Ring buffer of recently sent audio frames for echo RTT estimation.
# Each entry: (timestamp, rms_energy, byte_count)
_ECHO_RTT_HISTORY_SIZE = 200  # ~4s of 20ms frames
_ECHO_RTT_ENABLED = os.environ.get("ECHO_RTT_ENABLED", "false").lower() == "true"


def _rms_energy(pcm_bytes: bytes) -> float:
    """Compute RMS energy of PCM 16-bit LE audio. Returns 0.0-1.0 normalized."""
    if len(pcm_bytes) < 2:
        return 0.0
    import struct
    n_samples = len(pcm_bytes) // 2
    fmt = f"<{n_samples}h"
    try:
        samples = struct.unpack(fmt, pcm_bytes[: n_samples * 2])
    except struct.error:
        return 0.0
    if not samples:
        return 0.0
    sum_sq = sum(s * s for s in samples)
    rms = math.sqrt(sum_sq / n_samples)
    return min(rms / 32768.0, 1.0)


class PlivoPCMFrameSerializer(FrameSerializer):
    """Serializer for Plivo audio streaming using raw PCM 16kHz.

    No resampling, no mulaw conversion, no REST API calls.
    TTS must output PCM at 16kHz to match.
    """

    def __init__(self, stream_id: str, plivo_stream_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._stream_id = stream_id
        self._plivo_stream_id: str = plivo_stream_id
        self._audio_chunks_sent = 0
        self._total_bytes_serialized = 0
        self._total_bytes_received = 0

        # Echo RTT measurement: ring buffer of (timestamp, rms_energy, byte_count)
        self._sent_history: deque[tuple[float, float, int]] = deque(maxlen=_ECHO_RTT_HISTORY_SIZE)
        self._echo_rtt_samples: list[float] = []  # collected RTT measurements (ms)
        self._last_audio_sent_ts: float = 0.0  # timestamp of last outgoing audio frame

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            if self._plivo_stream_id:
                return json.dumps({"event": "clearAudio", "streamId": self._plivo_stream_id})
            return None

        if isinstance(frame, AudioRawFrame):
            payload = base64.b64encode(frame.audio).decode("utf-8")
            self._audio_chunks_sent += 1
            self._total_bytes_serialized += len(frame.audio)
            now = time.monotonic()
            self._last_audio_sent_ts = now

            # Phase 0: record outgoing frame energy for echo RTT measurement
            if _ECHO_RTT_ENABLED:
                energy = _rms_energy(frame.audio)
                self._sent_history.append((now, energy, len(frame.audio)))

            if self._audio_chunks_sent <= 5 or self._audio_chunks_sent % 100 == 0:
                logger.info(
                    f"PlivoPCM: serialize frame #{self._audio_chunks_sent}, "
                    f"bytes={len(frame.audio)}, frame_sr={frame.sample_rate}, "
                    f"plivo_sr={PLIVO_SAMPLE_RATE}, total_bytes={self._total_bytes_serialized}"
                )
            return json.dumps({
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-l16",
                    "sampleRate": PLIVO_SAMPLE_RATE,
                    "payload": payload,
                },
            })

        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Plivo JSON: {data}")
            return None

        event = message.get("event")

        if event == "start":
            self._plivo_stream_id = message.get("start", {}).get("streamId", "")
            logger.info(f"PlivoPCM: stream started, streamId={self._plivo_stream_id}")
            return None

        if event == "stop":
            bot_ms = self._total_bytes_serialized / (PLIVO_SAMPLE_RATE * 2) * 1000
            user_ms = self._total_bytes_received / (PLIVO_SAMPLE_RATE * 2) * 1000
            # Phase 0: log echo RTT summary
            rtt_summary = ""
            if self._echo_rtt_samples:
                sorted_rtt = sorted(self._echo_rtt_samples)
                p50 = sorted_rtt[len(sorted_rtt) // 2]
                p95 = sorted_rtt[int(len(sorted_rtt) * 0.95)]
                rtt_summary = (
                    f" | echo_rtt: n={len(sorted_rtt)}, "
                    f"min={sorted_rtt[0]:.0f}ms, p50={p50:.0f}ms, "
                    f"p95={p95:.0f}ms, max={sorted_rtt[-1]:.0f}ms"
                )
            logger.warning(
                f"PlivoPCM: TOTALS — bot: frames={self._audio_chunks_sent}, "
                f"bytes={self._total_bytes_serialized}, ms={bot_ms:.0f} | "
                f"user: bytes={self._total_bytes_received}, ms={user_ms:.0f}"
                f"{rtt_summary}"
            )
            return None

        # Phase 5 (deferred): Monitor Plivo buffer health
        if event == "degradedStream":
            pct = message.get("percentFull", "?")
            logger.warning(f"PlivoPCM: DegradedStream — buffer {pct}% full")
            return None

        if event == "playedStream":
            name = message.get("name", "")
            logger.info(f"PlivoPCM: playedStream checkpoint={name}")
            return None

        if event == "media":
            payload_b64 = message.get("media", {}).get("payload")
            if not payload_b64:
                return None

            audio_bytes = base64.b64decode(payload_b64)
            self._total_bytes_received += len(audio_bytes)

            # Phase 0: Echo RTT estimation — compare incoming energy to sent history.
            # High incoming energy shortly after high outgoing energy = echo.
            if _ECHO_RTT_ENABLED and self._sent_history:
                now = time.monotonic()
                in_energy = _rms_energy(audio_bytes)
                # Only measure when incoming audio has significant energy (likely echo)
                if in_energy > 0.02:
                    # Find the best-matching sent frame by energy proximity
                    best_rtt = None
                    best_diff = float("inf")
                    for sent_ts, sent_energy, _ in self._sent_history:
                        if sent_energy < 0.02:
                            continue  # skip silence frames
                        rtt_ms = (now - sent_ts) * 1000
                        if rtt_ms < 50 or rtt_ms > 3000:
                            continue  # implausible range
                        energy_diff = abs(in_energy - sent_energy)
                        if energy_diff < best_diff:
                            best_diff = energy_diff
                            best_rtt = rtt_ms
                    if best_rtt is not None and best_diff < 0.15:
                        self._echo_rtt_samples.append(best_rtt)
                        if len(self._echo_rtt_samples) <= 5 or len(self._echo_rtt_samples) % 50 == 0:
                            logger.info(
                                f"PlivoPCM: echo_rtt_sample={best_rtt:.0f}ms "
                                f"(energy_diff={best_diff:.3f}, n={len(self._echo_rtt_samples)})"
                            )

            return InputAudioRawFrame(
                audio=audio_bytes,
                sample_rate=PLIVO_SAMPLE_RATE,
                num_channels=1,
            )

        return None


class ComfortNoiseInjector:
    """Inject low-level pink noise during inter-sentence silence gaps.

    Runs as a background asyncio task. Monitors the serializer's
    _last_audio_sent_ts and sends comfort noise directly to the WebSocket
    when a gap > gap_threshold_ms is detected.

    Crucially, this bypasses the Pipecat pipeline entirely — frames go
    straight to the WebSocket. This avoids resetting BOT_VAD_STOP_SECS
    timer in BaseOutputTransport._handle_bot_speech(), so
    BotStoppedSpeakingFrame fires normally and the echo gate opens on schedule.

    Comfort noise is ~-55 dBFS pink noise (amplitude ~36 for int16).
    """

    def __init__(
        self,
        websocket,
        serializer: PlivoPCMFrameSerializer,
        bot_vad_stop_secs: float = 1.5,
        gap_threshold_ms: float = 200.0,
        enabled: bool = False,
    ):
        self._ws = websocket
        self._serializer = serializer
        self._bot_vad_stop_s = bot_vad_stop_secs
        self._gap_threshold_s = gap_threshold_ms / 1000.0
        self._enabled = enabled
        self._task: asyncio.Task | None = None
        self._total_noise_ms: float = 0.0
        # Pre-generate one frame of pink noise (~-55 dBFS)
        self._noise_frame = self._generate_noise_frame()

    @staticmethod
    def _generate_noise_frame() -> bytes:
        """Generate one 20ms frame of low-level pink noise as PCM int16 LE."""
        import random
        import struct

        n_samples = PLIVO_FRAME_BYTES // 2  # 320 samples for 20ms
        amplitude = 36  # ~-55 dBFS (36/32768 ≈ 0.0011)
        # Simple approximation of pink noise using filtered white noise
        samples = []
        b0 = b1 = b2 = 0.0
        for _ in range(n_samples):
            white = random.uniform(-1.0, 1.0)
            b0 = 0.99765 * b0 + white * 0.0990460
            b1 = 0.96300 * b1 + white * 0.2965164
            b2 = 0.57000 * b2 + white * 1.0526913
            pink = (b0 + b1 + b2 + white * 0.1848) * 0.11
            samples.append(int(max(-32768, min(32767, pink * amplitude))))
        return struct.pack(f"<{n_samples}h", *samples)

    def start(self):
        """Start the background comfort noise task."""
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._run())

    def stop(self):
        """Stop the background task."""
        if self._task:
            self._task.cancel()
            self._task = None
        if self._total_noise_ms > 0:
            logger.info(f"ComfortNoise: total injected={self._total_noise_ms:.0f}ms")

    async def _run(self):
        """Background loop: check for silence gaps and inject noise."""
        try:
            while True:
                await asyncio.sleep(0.02)  # Check every 20ms

                last_sent = self._serializer._last_audio_sent_ts
                if last_sent == 0.0:
                    continue

                now = time.monotonic()
                gap = now - last_sent

                # Only inject during inter-sentence gaps:
                # gap > threshold AND gap < BOT_VAD_STOP_SECS
                # (after BOT_VAD_STOP_SECS, bot speech is truly over — no noise needed)
                if gap > self._gap_threshold_s and gap < self._bot_vad_stop_s:
                    payload = base64.b64encode(self._noise_frame).decode("utf-8")
                    msg = json.dumps({
                        "event": "playAudio",
                        "media": {
                            "contentType": "audio/x-l16",
                            "sampleRate": PLIVO_SAMPLE_RATE,
                            "payload": payload,
                        },
                    })
                    try:
                        await self._ws.send_text(msg)
                        self._total_noise_ms += 20.0
                    except Exception:
                        break  # WebSocket closed

        except asyncio.CancelledError:
            pass
