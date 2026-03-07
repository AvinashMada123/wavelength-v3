"""
Transcript-based call guard for automatic detection of:
- Voicemail / answering machine
- Hold / IVR systems
- DND (Do Not Disturb) signals from user

Sits after STT in the pipeline, monitors TranscriptionFrame text.
On voicemail/hold detection: pushes EndFrame to terminate the call.
On DND detection: flags for post-call metadata (doesn't auto-hangup).
"""

from __future__ import annotations

import structlog
from pipecat.frames.frames import EndFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# Voicemail detection phrases (checked in first 2 user turns)
_VOICEMAIL_PHRASES = frozenset({
    "leave a message",
    "after the tone",
    "after the beep",
    "at the tone",
    "mailbox is full",
    "voicemail",
    "please record your message",
    "leave your name",
    "leave your message",
    "not available right now",
    "unavailable",
    "cannot take your call",
    "can't take your call",
    "message after",
})

# Hold/IVR detection phrases (checked in first 3 user turns)
_HOLD_IVR_PHRASES = frozenset({
    "please hold",
    "your call is important",
    "all agents are busy",
    "hold the line",
    "we will connect",
    "estimated wait",
    "for english press",
    "for hindi press",
    "main menu",
    "extension number",
    "dial the extension",
    "press 1",
    "press one",
    "press 2",
    "press two",
})

# DND — strong signals (permanent opt-out intent)
_DND_PHRASES_STRONG = frozenset({
    "don't call",
    "dont call",
    "stop calling",
    "never call",
    "do not call",
    "remove my number",
    "take me off",
    "block",
    "police",
    "complaint",
    "report",
    "mat karo call",
    "band karo",
    "unsubscribe",
})

# DND — soft signals (temporary disinterest)
_DND_PHRASES_SOFT = frozenset({
    "not interested",
    "don't need this",
    "dont need this",
    "waste of time",
    "don't want",
    "dont want",
})


class CallGuard(FrameProcessor):
    """Monitor STT transcripts for voicemail, hold/IVR, and DND signals.

    Properties after pipeline completes:
      end_reason: "voicemail" | "hold_ivr" | None
      dnd_detected: bool
      dnd_reason: str | None (e.g. "strong: stop calling")
    """

    def __init__(self, call_sid: str, **kwargs):
        super().__init__(name="CallGuard", **kwargs)
        self._call_sid = call_sid
        self._user_turn_count = 0
        self._end_reason: str | None = None
        self._dnd_detected = False
        self._dnd_reason: str | None = None
        self._ended = False

    @property
    def end_reason(self) -> str | None:
        return self._end_reason

    @property
    def dnd_detected(self) -> bool:
        return self._dnd_detected

    @property
    def dnd_reason(self) -> str | None:
        return self._dnd_reason

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import StartFrame

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        # Only check final transcription frames (not InterimTranscriptionFrame)
        if isinstance(frame, TranscriptionFrame) and not self._ended:
            text = frame.text.strip().lower()
            if text:
                self._user_turn_count += 1
                await self._check_transcript(text)

        await self.push_frame(frame, direction)

    async def _check_transcript(self, text: str):
        # Voicemail detection (first 2 turns only — voicemail greetings happen immediately)
        if self._user_turn_count <= 2:
            for phrase in _VOICEMAIL_PHRASES:
                if phrase in text:
                    logger.info("voicemail_detected", call_sid=self._call_sid, phrase=phrase, text=text[:100])
                    self._end_reason = "voicemail"
                    self._ended = True
                    await self.push_frame(EndFrame())
                    return

        # Hold/IVR detection (first 3 turns — IVR menus play early)
        if self._user_turn_count <= 3:
            for phrase in _HOLD_IVR_PHRASES:
                if phrase in text:
                    logger.info("hold_ivr_detected", call_sid=self._call_sid, phrase=phrase, text=text[:100])
                    self._end_reason = "hold_ivr"
                    self._ended = True
                    await self.push_frame(EndFrame())
                    return

        # DND detection (any turn) — flag for post-call metadata, don't auto-hangup
        # The LLM handles the conversation naturally; we just record the signal.
        if not self._dnd_detected:
            for phrase in _DND_PHRASES_STRONG:
                if phrase in text:
                    logger.info("dnd_detected", call_sid=self._call_sid, strength="strong", phrase=phrase)
                    self._dnd_detected = True
                    self._dnd_reason = f"strong: {phrase}"
                    return
            for phrase in _DND_PHRASES_SOFT:
                if phrase in text:
                    logger.info("dnd_detected", call_sid=self._call_sid, strength="soft", phrase=phrase)
                    self._dnd_detected = True
                    self._dnd_reason = f"soft: {phrase}"
                    return
