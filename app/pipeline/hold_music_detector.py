"""Hold music / carrier tone detector.

Detects the pattern: VAD reports audio activity but STT produces no
transcripts for an extended period. Real speech always produces transcripts;
hold music, carrier tones, and ringback do not.

Key invariant: permanently disabled once user has spoken.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    TTSSpeakFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class HoldMusicDetector(FrameProcessor):
    """Detect hold music: continuous VAD activity with no STT transcripts.

    - Tracks time since first VAD event without a corresponding transcript.
    - If VAD is active for `timeout` seconds with zero transcripts, it's hold music.
    - Permanently disabled once a real user transcript arrives.
    - Ignores VAD during bot speech (bot audio can trigger VAD).
    """

    def __init__(
        self,
        timeout: float = 15.0,
        call_sid: str = "",
        goodbye_text: str = "Looks like this is not a good time. I will try again later. Take care!",
        **kwargs,
    ):
        super().__init__(name="HoldMusicDetector", **kwargs)
        self._timeout = timeout
        self._call_sid = call_sid
        self._goodbye_text = goodbye_text
        self._bot_speaking: bool = False
        self._vad_active_since: float | None = None
        self._user_has_spoken: bool = False
        self._terminated: bool = False
        self._detector_task: asyncio.Task | None = None
        self._started: bool = False
        self._pipeline_task = None
        self._call_guard = None

    def set_task(self, task) -> None:
        self._pipeline_task = task

    def set_call_guard(self, guard) -> None:
        self._call_guard = guard

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            # Reset VAD tracking — bot speech can trigger VAD
            self._vad_active_since = None
            # Start detector loop on first bot speech (same trigger as others)
            if not self._started and not self._user_has_spoken:
                self._started = True
                self._detector_task = self.create_task(self._detector_loop())

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        elif isinstance(frame, UserStartedSpeakingFrame) and not self._bot_speaking:
            # VAD fired on non-bot audio — could be hold music or real speech
            if self._vad_active_since is None and not self._user_has_spoken:
                self._vad_active_since = time.monotonic()

        elif isinstance(frame, TranscriptionFrame) and not self._bot_speaking:
            if frame.text.strip():
                # Real transcript arrived — this is a person, not hold music
                self._user_has_spoken = True
                self._vad_active_since = None
                await self._stop_detector()

        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_detector()

        await self.push_frame(frame, direction)

    async def _stop_detector(self):
        if self._detector_task:
            await self.cancel_task(self._detector_task)
            self._detector_task = None

    async def _detector_loop(self):
        """Poll every 2s; fire if VAD active without transcripts for timeout."""
        try:
            while not self._user_has_spoken and not self._terminated:
                await asyncio.sleep(2.0)

                if self._user_has_spoken or self._terminated:
                    return

                # Check via call_guard too (belt and suspenders)
                if self._call_guard and self._call_guard.user_has_spoken:
                    self._user_has_spoken = True
                    return

                if self._bot_speaking:
                    continue

                if self._vad_active_since is None:
                    continue

                elapsed = time.monotonic() - self._vad_active_since
                if elapsed < self._timeout:
                    continue

                # Hold music detected
                self._terminated = True
                logger.info(
                    "hold_music_detected",
                    call_sid=self._call_sid,
                    vad_without_transcript_s=round(elapsed, 1),
                )
                if self._call_guard:
                    self._call_guard.set_termination_source("hold_music")
                await self.push_frame(TTSSpeakFrame(text=self._goodbye_text))
                await asyncio.sleep(3.0)
                if self._pipeline_task:
                    await self._pipeline_task.queue_frame(EndFrame())
                else:
                    await self.push_frame(EndFrame())
                return

        except asyncio.CancelledError:
            pass

    async def cleanup(self) -> None:
        await super().cleanup()
        await self._stop_detector()
