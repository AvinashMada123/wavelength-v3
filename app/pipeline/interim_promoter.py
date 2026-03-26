"""Promote interim transcripts to final on VAD stop for faster LLM start.

When VAD detects the user stopped speaking, the latest interim transcript
is promoted to a final TranscriptionFrame immediately — without waiting
for Deepgram's utterance_end_ms timeout. This saves 300-700ms per turn.

If the real final transcript arrives later and differs, it's too late
(LLM already started). In practice, the interim at VAD-stop is almost
always identical to the final because the user has already finished
their utterance.

Insert between STT and the rest of the pipeline.
"""

from __future__ import annotations

import time

import structlog
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger()


class InterimTranscriptPromoter(FrameProcessor):
    """Promotes the latest interim transcript to final on UserStoppedSpeaking.

    Flow:
    1. Buffers the latest InterimTranscriptionFrame text (overwrites on each new one)
    2. On UserStoppedSpeakingFrame: if we have a buffered interim AND no final
       has arrived yet for this utterance, emit a synthetic TranscriptionFrame
    3. When the real TranscriptionFrame arrives: if we already promoted, suppress
       the duplicate (unless the text differs significantly)
    """

    def __init__(self, call_sid: str = "", enabled: bool = True, **kwargs):
        super().__init__(name="InterimTranscriptPromoter", **kwargs)
        self._call_sid = call_sid
        self._enabled = enabled
        self._latest_interim: str = ""
        self._promoted_text: str | None = None
        self._user_speaking = False

    async def process_frame(self, frame, direction: FrameDirection):
        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        if not self._enabled:
            await self.push_frame(frame, direction)
            return

        # Buffer latest interim text
        if isinstance(frame, InterimTranscriptionFrame):
            if frame.text and frame.text.strip():
                self._latest_interim = frame.text
                self._user_speaking = True
            # Pass interim through (other processors may use it)
            await self.push_frame(frame, direction)
            return

        # On VAD stop: promote interim to final
        if isinstance(frame, UserStoppedSpeakingFrame):
            if self._latest_interim and self._promoted_text is None:
                # Promote: emit synthetic TranscriptionFrame
                self._promoted_text = self._latest_interim
                logger.info(
                    "interim_promoted",
                    call_sid=self._call_sid,
                    text=self._promoted_text[:80],
                )
                promoted = TranscriptionFrame(
                    text=self._promoted_text,
                    user_id="",
                    timestamp="",
                )
                await self.push_frame(promoted, direction)
            self._user_speaking = False
            await self.push_frame(frame, direction)
            return

        # Real final transcript arrived
        if isinstance(frame, TranscriptionFrame):
            if self._promoted_text is not None:
                # We already promoted an interim. Check if final differs.
                if frame.text and frame.text.strip() != self._promoted_text.strip():
                    # Final differs — pass it through (LLM will get updated text)
                    logger.info(
                        "interim_final_mismatch",
                        call_sid=self._call_sid,
                        promoted=self._promoted_text[:60],
                        final=frame.text[:60] if frame.text else "",
                    )
                    self._promoted_text = None
                    self._latest_interim = ""
                    await self.push_frame(frame, direction)
                    return
                else:
                    # Final matches promoted — suppress duplicate
                    self._promoted_text = None
                    self._latest_interim = ""
                    return  # Don't push duplicate
            else:
                # No promotion happened — pass final through normally
                self._latest_interim = ""
                await self.push_frame(frame, direction)
                return

        await self.push_frame(frame, direction)
