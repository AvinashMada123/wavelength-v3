"""Reliable silence watchdog that ends calls after prolonged user inactivity.

Replaces the deprecated UserIdleProcessor which fails to fire in certain
configurations (e.g., Sarvam STT with server-side VAD). Uses a simple
polling-based timer instead of event-based waiting.
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
    StartFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class SilenceWatchdog(FrameProcessor):
    """Ends the call after prolonged silence from the user.

    Escalation:
      1st timeout  → "Hello? Are you there?"
      2nd timeout  → Goodbye message → EndFrame (hang up)

    The timer only counts when the bot is NOT speaking. Echo transcripts
    during bot speech do not reset the escalation level.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        call_sid: str = "",
        prompt_text: str = "Hello? Can you hear me?",
        goodbye_text: str = "Looks like this is not a good time. I will try again later. Take care!",
        **kwargs,
    ):
        super().__init__(name="SilenceWatchdog", **kwargs)
        self._timeout = timeout
        self._call_sid = call_sid
        self._prompt_text = prompt_text
        self._goodbye_text = goodbye_text
        self._last_activity: float = 0.0
        self._bot_speaking: bool = False
        self._escalation: int = 0
        self._started: bool = False
        self._watchdog_task: asyncio.Task | None = None
        self._pipeline_task = None  # Set after PipelineTask creation
        self._call_guard = None  # Set after CallGuard creation

    def set_task(self, task) -> None:
        """Store a reference to the PipelineTask for proper EndFrame delivery."""
        self._pipeline_task = task

    def set_call_guard(self, guard) -> None:
        """Store a reference to CallGuard for termination_source tracking."""
        self._call_guard = guard

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # --- Track bot speaking state ---
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._last_activity = time.monotonic()

        # --- Real user speech (not echo during bot speech) ---
        if isinstance(frame, TranscriptionFrame) and not self._bot_speaking:
            self._last_activity = time.monotonic()
            self._escalation = 0  # User spoke — reset escalation

        if isinstance(frame, UserStartedSpeakingFrame) and not self._bot_speaking:
            self._last_activity = time.monotonic()
            self._escalation = 0

        # --- Start watchdog after first bot speech (greeting) ---
        if isinstance(frame, BotStartedSpeakingFrame) and not self._started:
            self._started = True
            self._last_activity = time.monotonic()
            self._watchdog_task = self.create_task(self._watchdog_loop())

        # --- Clean up on EndFrame ---
        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_watchdog()

        await self.push_frame(frame, direction)

    async def _stop_watchdog(self):
        if self._watchdog_task:
            await self.cancel_task(self._watchdog_task)
            self._watchdog_task = None

    async def _watchdog_loop(self):
        """Poll every second; fire escalation after timeout of no activity."""
        try:
            while True:
                await asyncio.sleep(1.0)

                if self._bot_speaking:
                    continue

                elapsed = time.monotonic() - self._last_activity
                if elapsed < self._timeout:
                    continue

                self._escalation += 1

                if self._escalation == 1:
                    logger.info(
                        "silence_watchdog_prompt",
                        call_sid=self._call_sid,
                        elapsed_s=round(elapsed, 1),
                    )
                    await self.push_frame(TTSSpeakFrame(text=self._prompt_text))
                    # Reset activity so next timeout counts from now
                    self._last_activity = time.monotonic()

                elif self._escalation >= 2:
                    logger.info(
                        "silence_watchdog_hangup",
                        call_sid=self._call_sid,
                        elapsed_s=round(elapsed, 1),
                    )
                    if self._call_guard:
                        self._call_guard.set_termination_source("silence_watchdog")
                    await self.push_frame(
                        TTSSpeakFrame(text=self._goodbye_text)
                    )
                    # Give TTS time to play goodbye before ending
                    await asyncio.sleep(4.0)
                    # Must use queue_frame on the PipelineTask (not push_frame)
                    # so EndFrame is properly broadcast to all processors
                    if self._pipeline_task:
                        await self._pipeline_task.queue_frame(EndFrame())
                    else:
                        await self.push_frame(EndFrame())
                    return

        except asyncio.CancelledError:
            pass

    async def cleanup(self) -> None:
        await super().cleanup()
        await self._stop_watchdog()
