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

import re

import structlog
from pipecat.frames.frames import EndFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# Voicemail detection phrases (checked in first 2 conversational turns)
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
    "cannot take your call",
    "can't take your call",
    "message after",
    # Indian carrier phrases
    "the number you have dialed",
    "subscriber you have dialed",
    "is currently switched off",
    "is out of coverage area",
    "number does not exist",
    "number is not in service",
})

# Phrases only checked on the very first STT segment (turn 1).
# These are common in voicemail greetings but also in normal human speech
# at later turns (e.g., "I'm not available right now, call me later").
_VOICEMAIL_TURN1_ONLY = frozenset({
    "not available right now",
    "unavailable",
})

# Hold/IVR detection phrases (checked in first 3 conversational turns)
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
    "please stay on the line",
    "routing your call",
    "connecting you",
    "transferring your call",
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

# First-person pronouns — if present in transcript, it's likely a real person
# speaking, not a carrier/voicemail recording. Used to skip voicemail detection.
_FIRST_PERSON_RE = re.compile(r"\b(i'm|i am|my |me |we )\b", re.IGNORECASE)


class CallGuard(FrameProcessor):
    """Monitor STT transcripts for voicemail, hold/IVR, and DND signals.

    Properties after pipeline completes:
      end_reason: "voicemail" | "hold_ivr" | None
      dnd_detected: bool
      dnd_reason: str | None (e.g. "strong: stop calling")
      detected_red_flags: list[dict] — accumulated real-time red flag detections
      llm_end_reason: str | None — reason from LLM's end_call tool invocation
      termination_source: str | None — which path ended the call (write-once)
    """

    def __init__(self, call_sid: str, goal_config: dict | None = None, **kwargs):
        super().__init__(name="CallGuard", **kwargs)
        self._call_sid = call_sid
        self._user_turn_count = 0
        self._bot_has_spoken = False  # Track conversational turns, not STT segments
        self._end_reason: str | None = None
        self._dnd_detected = False
        self._dnd_reason: str | None = None
        self._ended = False
        self.llm_end_reason: str | None = None
        self._termination_source: str | None = None
        self._user_has_spoken: bool = False

        # Custom keyword-based red flags from goal_config (realtime only)
        self._custom_realtime_flags: list[dict] = []
        if goal_config:
            for rf in goal_config.get("red_flags", []):
                if rf.get("detect_in") == "realtime" and rf.get("keywords"):
                    self._custom_realtime_flags.append(rf)
        self.detected_red_flags: list[dict] = []

    @property
    def end_reason(self) -> str | None:
        return self._end_reason

    @property
    def dnd_detected(self) -> bool:
        return self._dnd_detected

    @property
    def dnd_reason(self) -> str | None:
        return self._dnd_reason

    @property
    def termination_source(self) -> str | None:
        return self._termination_source

    @property
    def user_has_spoken(self) -> bool:
        """True once a real user transcript arrives after bot has spoken."""
        return self._user_has_spoken

    def set_termination_source(self, source: str) -> None:
        """Write-once setter — first caller wins to avoid race conditions."""
        if self._termination_source is None:
            self._termination_source = source

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import BotStartedSpeakingFrame, StartFrame

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        # Track when bot has spoken (upstream frame from transport.output).
        # Used to distinguish carrier recordings (multiple STT segments before
        # bot speaks = turn 0) from real conversational turns.
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_has_spoken = True
            await self.push_frame(frame, direction)
            return

        # Only check final transcription frames (not InterimTranscriptionFrame)
        if isinstance(frame, TranscriptionFrame) and not self._ended:
            text = frame.text.strip().lower()
            if text:
                # Only increment turn count when user speaks AFTER bot has spoken.
                # A carrier recording producing 3 STT segments before the bot
                # speaks stays at turn 0 — all segments are pre-conversation.
                if self._bot_has_spoken:
                    self._user_turn_count += 1
                    self._bot_has_spoken = False
                    self._user_has_spoken = True
                await self._check_transcript(text)

        await self.push_frame(frame, direction)

    async def _check_transcript(self, text: str):
        # Pronoun guard for voicemail: if transcript contains first-person
        # pronouns, it's likely a real human, not a carrier recording.
        # Only applies to voicemail detection, NOT IVR (IVR says "I'll connect you").
        has_first_person = bool(_FIRST_PERSON_RE.search(text))

        # Voicemail detection (first 2 conversational turns)
        if self._user_turn_count <= 2 and not has_first_person:
            for phrase in _VOICEMAIL_PHRASES:
                if phrase in text:
                    logger.info("voicemail_detected", call_sid=self._call_sid, phrase=phrase, text=text[:100])
                    self._end_reason = "voicemail"
                    self.set_termination_source("voicemail")
                    self._ended = True
                    await self.push_frame(EndFrame())
                    return

            # Turn-1-only phrases: common in voicemail but also in human speech
            if self._user_turn_count <= 1:
                for phrase in _VOICEMAIL_TURN1_ONLY:
                    if phrase in text:
                        logger.info("voicemail_detected", call_sid=self._call_sid, phrase=phrase, text=text[:100])
                        self._end_reason = "voicemail"
                        self.set_termination_source("voicemail")
                        self._ended = True
                        await self.push_frame(EndFrame())
                        return

        # Hold/IVR detection (first 3 conversational turns — no pronoun guard,
        # IVR systems commonly use first-person like "I'll connect you")
        if self._user_turn_count <= 3:
            for phrase in _HOLD_IVR_PHRASES:
                if phrase in text:
                    logger.info("hold_ivr_detected", call_sid=self._call_sid, phrase=phrase, text=text[:100])
                    self._end_reason = "hold_ivr"
                    self.set_termination_source("hold_ivr")
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
                    break
            if not self._dnd_detected:
                for phrase in _DND_PHRASES_SOFT:
                    if phrase in text:
                        logger.info("dnd_detected", call_sid=self._call_sid, strength="soft", phrase=phrase)
                        self._dnd_detected = True
                        self._dnd_reason = f"soft: {phrase}"
                        break

        # Custom real-time red flag detection (keyword-based only, no LLM)
        detected_ids = {rf["id"] for rf in self.detected_red_flags}
        for rf_config in self._custom_realtime_flags:
            rf_id = rf_config["id"]
            if rf_id in detected_ids:
                continue  # Already detected this flag
            for keyword in rf_config.get("keywords", []):
                if keyword.lower() in text:
                    detection = {
                        "id": rf_id,
                        "severity": rf_config.get("severity", "medium"),
                        "evidence": text[:200],
                        "turn_index": self._user_turn_count,
                    }
                    self.detected_red_flags.append(detection)
                    logger.info(
                        "custom_red_flag_detected",
                        call_sid=self._call_sid,
                        flag_id=rf_id,
                        severity=rf_config.get("severity"),
                        keyword=keyword,
                    )
                    break  # One match per flag is enough
