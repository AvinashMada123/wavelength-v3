"""Early hangup timer for pre-conversation calls.

Independent safety net: if no real user speech arrives within a configurable
timeout after the greeting starts, terminate the call. Catches voicemail,
hold music, and unreachable numbers that other detectors miss.

Key invariant: cancelled permanently on first real user transcript.
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
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class EarlyHangupTimer(FrameProcessor):
    """Terminate call if no real user speech within timeout of greeting start.

    - Starts on first BotStartedSpeakingFrame (greeting).
    - Cancelled permanently on first TranscriptionFrame while bot is not speaking.
    - Independent of SilenceWatchdog — does not reset when bot speaks.
    """

    def __init__(
        self,
        timeout: float = 25.0,
        call_sid: str = "",
        goodbye_text: str = "Looks like this is not a good time. I will try again later. Take care!",
        **kwargs,
    ):
        super().__init__(name="EarlyHangupTimer", **kwargs)
        self._timeout = timeout
        self._call_sid = call_sid
        self._goodbye_text = goodbye_text
        self._bot_speaking: bool = False
        self._started: bool = False
        self._cancelled: bool = False
        self._timer_task: asyncio.Task | None = None
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
            if not self._started and not self._cancelled:
                self._started = True
                self._timer_task = self.create_task(self._timer_loop())

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        # Real user speech — cancel timer permanently
        elif isinstance(frame, TranscriptionFrame) and not self._bot_speaking:
            if frame.text.strip() and not self._cancelled:
                self._cancelled = True
                await self._stop_timer()
                logger.info(
                    "early_hangup_cancelled",
                    call_sid=self._call_sid,
                    reason="user_spoke",
                )

        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_timer()

        await self.push_frame(frame, direction)

    async def _stop_timer(self):
        if self._timer_task:
            await self.cancel_task(self._timer_task)
            self._timer_task = None

    async def _timer_loop(self):
        """Wait for timeout, then terminate if user still hasn't spoken."""
        try:
            await asyncio.sleep(self._timeout)

            if self._cancelled:
                return

            # Double-check via call_guard (belt and suspenders)
            if self._call_guard and self._call_guard.user_has_spoken:
                return

            logger.info(
                "early_hangup_fired",
                call_sid=self._call_sid,
                timeout_s=self._timeout,
            )
            if self._call_guard:
                self._call_guard.set_termination_source("early_hangup_no_speech")
            await self.push_frame(TTSSpeakFrame(text=self._goodbye_text))
            await asyncio.sleep(4.0)
            if self._pipeline_task:
                await self._pipeline_task.queue_frame(EndFrame())
            else:
                await self.push_frame(EndFrame())

        except asyncio.CancelledError:
            pass

    async def cleanup(self) -> None:
        await super().cleanup()
        await self._stop_timer()
