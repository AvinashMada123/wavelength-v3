"""
Custom Pipecat TTSService that uses Google Cloud TTS gRPC streaming_synthesize().

Uses Chirp3-HD model exclusively (the only model that supports streaming synthesis).
Outputs raw PCM 16-bit audio — PlivoFrameSerializer converts to MULAW internally.
Falls back to REST synthesize_speech() if gRPC stream fails.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from google.cloud import texttospeech_v1
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

logger = structlog.get_logger(__name__)

_ENCODING_MAP = {
    "PCM": texttospeech_v1.AudioEncoding.PCM,
    "LINEAR16": texttospeech_v1.AudioEncoding.LINEAR16,
    "MULAW": texttospeech_v1.AudioEncoding.MULAW,
    "ALAW": texttospeech_v1.AudioEncoding.ALAW,
}


class GoogleCloudGRPCTTSService(TTSService):
    """
    Streams text to audio via Google Cloud TTS gRPC streaming_synthesize().

    One gRPC stream per sentence — Pipecat's base TTSService calls run_tts()
    per sentence (it splits LLM output at sentence boundaries).
    Audio chunks are yielded immediately as they arrive (no buffering).
    """

    def __init__(
        self,
        voice_name: str = "en-IN-Chirp3-HD-Kore",
        language_code: str = "en-IN",
        sample_rate: int = 16000,
        audio_encoding: str = "PCM",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._voice_name = voice_name
        self._language_code = language_code
        self._sample_rate = sample_rate
        self._audio_encoding = audio_encoding
        self._speaking_rate = speaking_rate
        self._pitch = pitch
        self._client: TextToSpeechAsyncClient | None = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._client = TextToSpeechAsyncClient()
        logger.info(
            "google_cloud_tts_started",
            voice=self._voice_name,
            sample_rate=self._sample_rate,
            encoding=self._audio_encoding,
        )

    async def stop(self, frame: EndFrame):
        self._client = None
        await super().stop(frame)

    def _get_encoding_enum(self) -> texttospeech_v1.AudioEncoding:
        return _ENCODING_MAP[self._audio_encoding]

    async def run_tts(self, text: str, context_id: str | None = None) -> AsyncGenerator[Frame, None]:
        yield TTSStartedFrame()

        try:
            async for audio_chunk in self._stream_synthesize(text):
                yield TTSAudioRawFrame(
                    audio=audio_chunk,
                    sample_rate=self._sample_rate,
                    num_channels=1,
                )
        except Exception as e:
            logger.error("grpc_tts_streaming_failed", error=str(e), text_length=len(text))
            audio_data = await self._rest_synthesize_fallback(text)
            if audio_data:
                yield TTSAudioRawFrame(
                    audio=audio_data,
                    sample_rate=self._sample_rate,
                    num_channels=1,
                )

        yield TTSStoppedFrame()

    async def _ensure_client(self):
        """Lazily initialize the gRPC client if not yet created."""
        if self._client is None:
            self._client = TextToSpeechAsyncClient()

    async def _stream_synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """Open a gRPC streaming_synthesize call for a single sentence."""
        await self._ensure_client()
        config = texttospeech_v1.StreamingSynthesizeConfig(
            voice=texttospeech_v1.VoiceSelectionParams(
                language_code=self._language_code,
                name=self._voice_name,
            ),
            streaming_audio_config=texttospeech_v1.StreamingAudioConfig(
                audio_encoding=self._get_encoding_enum(),
                sample_rate_hertz=self._sample_rate,
                speaking_rate=self._speaking_rate,
            ),
        )

        async def request_generator():
            # First message: config only
            yield texttospeech_v1.StreamingSynthesizeRequest(streaming_config=config)
            # Second message: text input
            yield texttospeech_v1.StreamingSynthesizeRequest(
                input=texttospeech_v1.StreamingSynthesisInput(text=text)
            )

        responses = await self._client.streaming_synthesize(requests=request_generator())

        async for response in responses:
            if response.audio_content:
                yield response.audio_content

    async def _rest_synthesize_fallback(self, text: str) -> bytes | None:
        """Fallback: non-streaming synthesize_speech() call."""
        try:
            await self._ensure_client()
            response = await self._client.synthesize_speech(
                input=texttospeech_v1.SynthesisInput(text=text),
                voice=texttospeech_v1.VoiceSelectionParams(
                    language_code=self._language_code,
                    name=self._voice_name,
                ),
                audio_config=texttospeech_v1.AudioConfig(
                    audio_encoding=self._get_encoding_enum(),
                    sample_rate_hertz=self._sample_rate,
                    speaking_rate=self._speaking_rate,
                    pitch=self._pitch,
                ),
            )
            return response.audio_content
        except Exception as e:
            logger.error("rest_tts_fallback_failed", error=str(e))
            return None
