"""Smallest AI Pulse STT — custom Pipecat STTService via WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
import time

import structlog
import websockets

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.services.ai_services import STTService
from pipecat.utils.time import time_now_iso8601

logger = structlog.get_logger(__name__)

SMALLEST_WS_URL = "wss://waves-api.smallest.ai/api/v1/pulse/get_text"
KEEPALIVE_INTERVAL = 5.0  # seconds
KEEPALIVE_SILENCE_DURATION = 0.1  # 100ms of silence


class SmallestSTTService(STTService):
    """Real-time speech-to-text using Smallest AI Pulse via WebSocket."""

    def __init__(
        self,
        *,
        api_key: str,
        language: str = "en",
        sample_rate: int = 16000,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._language = language
        self._sample_rate = sample_rate
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._receive_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._last_audio_time: float = 0
        self._connected = False

    async def process_frame(self, frame, direction):
        """Override to connect on StartFrame and disconnect on End/Cancel."""
        if isinstance(frame, StartFrame):
            await self._connect()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._disconnect()

        await super().process_frame(frame, direction)

    async def _connect(self):
        """Open WebSocket connection to Smallest AI Pulse."""
        try:
            url = (
                f"{SMALLEST_WS_URL}"
                f"?model=pulse"
                f"&language={self._language}"
                f"&sample_rate={self._sample_rate}"
            )
            headers = {"Authorization": f"Bearer {self._api_key}"}

            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                max_size=2**20,  # 1MB
            )
            self._connected = True
            self._last_audio_time = time.monotonic()

            # Start background receive task
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            logger.info(
                "smallest_stt_connected",
                language=self._language,
                sample_rate=self._sample_rate,
            )
        except Exception as e:
            logger.error("smallest_stt_connect_failed", error=str(e))
            self._connected = False

    async def _disconnect(self):
        """Close WebSocket connection."""
        self._connected = False

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("smallest_stt_disconnected")

    async def run_stt(self, audio: bytes) -> asyncio.AsyncGenerator[Frame, None]:
        """Send raw PCM audio bytes to Pulse via WebSocket."""
        if not self._ws or not self._connected:
            yield ErrorFrame(error="Smallest STT not connected")
            return

        try:
            await self._ws.send(audio)
            self._last_audio_time = time.monotonic()
        except websockets.ConnectionClosed:
            logger.warning("smallest_stt_connection_closed_during_send")
            self._connected = False
            # Try to reconnect
            asyncio.create_task(self._reconnect())
        except Exception as e:
            yield ErrorFrame(error=f"Smallest STT send error: {e}")

        yield None

    async def _receive_loop(self):
        """Background task: read transcript messages from WebSocket."""
        while self._connected and self._ws:
            try:
                msg = await self._ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    await self._handle_message(data)
            except websockets.ConnectionClosed:
                if self._connected:
                    logger.warning("smallest_stt_connection_lost")
                    asyncio.create_task(self._reconnect())
                break
            except json.JSONDecodeError:
                logger.warning("smallest_stt_invalid_json", raw=str(msg)[:200])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("smallest_stt_receive_error", error=str(e))

    async def _handle_message(self, data: dict):
        """Process a transcript message from Pulse."""
        text = data.get("text", "").strip()
        is_final = data.get("is_final", True)

        if not text:
            return

        if is_final:
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id="",
                    timestamp=time_now_iso8601(),
                )
            )
        else:
            await self.push_frame(
                InterimTranscriptionFrame(
                    text=text,
                    user_id="",
                    timestamp=time_now_iso8601(),
                )
            )

    async def _keepalive_loop(self):
        """Send periodic silence to prevent connection timeout."""
        while self._connected:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if not self._ws or not self._connected:
                    break

                elapsed = time.monotonic() - self._last_audio_time
                if elapsed < KEEPALIVE_INTERVAL:
                    continue

                # Send 100ms of silent PCM (16kHz, 16-bit mono)
                num_samples = int(self._sample_rate * KEEPALIVE_SILENCE_DURATION)
                silence = b"\x00" * (num_samples * 2)
                await self._ws.send(silence)
                self._last_audio_time = time.monotonic()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("smallest_stt_keepalive_error", error=str(e))

    async def _reconnect(self):
        """Attempt to reconnect after connection loss."""
        if self._connected:
            return  # Already reconnecting or connected
        logger.info("smallest_stt_reconnecting")
        await asyncio.sleep(1.0)
        await self._connect()
