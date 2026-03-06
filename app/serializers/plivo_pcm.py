"""
Stateless Plivo PCM 16kHz frame serializer.

Plivo bidirectional streams use raw PCM 16-bit signed LE at 16kHz
(contentType="audio/x-l16;rate=16000"). No mulaw conversion needed.
"""

from __future__ import annotations

import base64
import json
import wave
from pathlib import Path

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


class PlivoPCMFrameSerializer(FrameSerializer):
    """Serializer for Plivo audio streaming using raw PCM 16kHz.

    No resampling, no mulaw conversion, no REST API calls.
    TTS must output PCM at 16kHz to match.
    """

    def __init__(self, stream_id: str, *, debug_wav: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._stream_id = stream_id
        self._plivo_stream_id: str = ""
        self._audio_chunks_sent = 0
        self._total_bytes_serialized = 0
        self._wav_file: wave.Wave_write | None = None
        if debug_wav:
            wav_dir = Path("debug_audio")
            wav_dir.mkdir(exist_ok=True)
            wav_path = wav_dir / f"{stream_id}.wav"
            self._wav_file = wave.open(str(wav_path), "wb")
            self._wav_file.setnchannels(1)
            self._wav_file.setsampwidth(2)  # 16-bit
            self._wav_file.setframerate(PLIVO_SAMPLE_RATE)
            logger.info(f"PlivoPCM: recording outbound audio to {wav_path}")

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            if self._plivo_stream_id:
                return json.dumps({"event": "clearAudio", "streamId": self._plivo_stream_id})
            return None

        if isinstance(frame, AudioRawFrame):
            payload = base64.b64encode(frame.audio).decode("utf-8")
            self._audio_chunks_sent += 1
            self._total_bytes_serialized += len(frame.audio)
            if self._audio_chunks_sent <= 5 or self._audio_chunks_sent % 100 == 0:
                logger.info(
                    f"PlivoPCM: serialize frame #{self._audio_chunks_sent}, "
                    f"bytes={len(frame.audio)}, total_bytes={self._total_bytes_serialized}"
                )
            if self._wav_file:
                self._wav_file.writeframes(frame.audio)
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

    def close_wav(self):
        logger.warning(
            f"PlivoPCM: SERIALIZE TOTAL — frames={self._audio_chunks_sent}, "
            f"bytes={self._total_bytes_serialized}, "
            f"ms={self._total_bytes_serialized / (16000 * 2) * 1000:.0f}"
        )
        if self._wav_file:
            self._wav_file.close()
            self._wav_file = None
            logger.info(f"PlivoPCM: WAV recording closed ({self._audio_chunks_sent} chunks)")

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
            self.close_wav()
            return None

        if event == "media":
            payload_b64 = message.get("media", {}).get("payload")
            if not payload_b64:
                return None

            audio_bytes = base64.b64decode(payload_b64)
            return InputAudioRawFrame(
                audio=audio_bytes,
                sample_rate=PLIVO_SAMPLE_RATE,
                num_channels=1,
            )

        return None
