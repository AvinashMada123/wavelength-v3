"""
Build a per-call Pipecat pipeline from bot config and call context.

Returns (PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext).
"""

from __future__ import annotations

import asyncio
import time

import pipecat.transports.base_output as _base_output
import structlog
from deepgram import LiveOptions

# Widen bot-stop window to tolerate Sarvam TTS inter-phrase gaps (~700-1500ms).
# Without this, Pipecat's default 0.35s triggers false "bot stopped speaking"
# mid-sentence, clearing audio buffers and causing audible drops.
# Safe because interruptions use MinWordsInterruptionStrategy (transcript-based),
# not bot-speaking state. EchoGate is NOT in the pipeline.
_base_output.BOT_VAD_STOP_SECS = 1.5

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.interruptions.min_words_interruption_strategy import MinWordsInterruptionStrategy
from pipecat.frames.frames import EndFrame, TTSUpdateSettingsFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from app.serializers.plivo_pcm import PlivoPCMFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.llm_vertex import GoogleVertexLLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from starlette.websockets import WebSocket

from app.config import settings
from app.models.bot_config import BotConfig
from app.models.schemas import CallContext
from app.pipeline.call_guard import CallGuard
from app.pipeline.phrase_aggregator import PhraseTextAggregator
from app.pipeline.silence_watchdog import SilenceWatchdog

_timing_logger = structlog.get_logger("pipeline.timing")
logger = structlog.get_logger(__name__)

# Backward-compat mapping: Chirp3-HD voice names → Gemini TTS voice names
_CHIRP_TO_GEMINI_VOICE = {
    "en-IN-Chirp3-HD-Kore": "Kore",
    "en-IN-Chirp3-HD-Leda": "Leda",
    "en-IN-Chirp3-HD-Aoede": "Aoede",
    "en-IN-Chirp3-HD-Charon": "Charon",
    "en-IN-Chirp3-HD-Fenrir": "Fenrir",
    "en-IN-Chirp3-HD-Puck": "Puck",
}

_DEFAULT_STYLE_PROMPT = (
    "Speak warmly in Indian English. Natural, calm, conversational tone. "
    "Never robotic."
)

# Minimal universal guardrails appended to every system prompt.
_CONVERSATION_RULES = """

UNIVERSAL PHONE RULES (always follow):
- HARD LIMIT: Maximum 2 sentences per turn, then STOP and let the customer speak.
- Ask at most 1 question per turn.
- NEVER repeat a question you already asked, even rephrased.
- If the user says they already answered, already have the details, is not interested, asks not to be called again, or says they are busy, driving, or unwell, acknowledge briefly and end the call.

"""

# Map BCP-47 language codes → pipecat Language enum names
_LANG_CODE_TO_ENUM = {
    "en-IN": "EN_IN",
    "en-US": "EN_US",
    "en-GB": "EN_GB",
    "hi-IN": "HI_IN",
    "ta-IN": "TA_IN",
    "te-IN": "TE_IN",
    "bn-IN": "BN_IN",
    "kn-IN": "KN_IN",
    "ml-IN": "ML_IN",
    "gu-IN": "GU_IN",
}


class GreetingGuard(FrameProcessor):
    """Suppress phantom UserStoppedSpeakingFrame during the initial greeting.

    Plivo echoes bot audio back through WebSocket. Silero VAD detects this echo
    as "speech" and fires UserStoppedSpeakingFrame within 0.1-0.2s of greeting
    start. This causes the context aggregator to push to LLM, generating a
    phantom response that overlaps with the greeting ("weird noises").

    This guard drops UserStoppedSpeakingFrame for a configurable duration after
    pipeline start. Real TranscriptionFrames still pass through and accumulate
    in the aggregator — they'll be pushed on the next real user turn boundary.
    """

    def __init__(self, guard_duration: float = 5.0, call_sid: str = "", **kwargs):
        super().__init__(name="GreetingGuard", **kwargs)
        self._guard_duration = guard_duration
        self._call_sid = call_sid
        self._start_time: float | None = None
        self._guard_active = True

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import StartFrame, UserStoppedSpeakingFrame

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            self._start_time = time.monotonic()
            await self.push_frame(frame, direction)
            return

        # Drop UserStoppedSpeakingFrame during guard period
        if isinstance(frame, UserStoppedSpeakingFrame) and self._guard_active:
            if self._start_time is not None:
                elapsed = time.monotonic() - self._start_time
                if elapsed < self._guard_duration:
                    logger.debug(
                        "greeting_guard_suppressed",
                        call_sid=self._call_sid,
                        elapsed=round(elapsed, 2),
                    )
                    return  # Drop the frame — phantom VAD from echo
            self._guard_active = False

        await self.push_frame(frame, direction)


class EchoGate(FrameProcessor):
    """Audio gate that mutes incoming audio during bot speech to suppress echo.

    Plivo echoes bot audio back through the WebSocket. Without gating, this
    echo reaches STT, gets transcribed, and can trigger false interruptions.

    Gate closes on BotStartedSpeakingFrame and opens after
    BotStoppedSpeakingFrame + echo_tail_ms. If a new BotStartedSpeakingFrame
    arrives during the echo tail timer, the gate stays closed (bridges
    inter-sentence TTS gaps).

    Safety valve: force-opens after 30s to prevent stuck-closed state.
    """

    def __init__(
        self,
        echo_tail_ms: float = 300.0,
        call_sid: str = "",
        enabled: bool = True,
        **kwargs,
    ):
        super().__init__(name="EchoGate", **kwargs)
        self._call_sid = call_sid
        self._enabled = enabled
        self._echo_tail_s = echo_tail_ms / 1000.0
        self._gate_closed = False
        self._gate_closed_at: float | None = None
        self._echo_tail_task: asyncio.Task | None = None
        self._frames_silenced = 0
        self._total_silenced = 0
        self._safety_limit_s = 30.0

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
            EndFrame,
            InputAudioRawFrame,
            StartFrame,
        )

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, EndFrame):
            if self._echo_tail_task and not self._echo_tail_task.done():
                self._echo_tail_task.cancel()
                self._echo_tail_task = None
            await self.push_frame(frame, direction)
            return

        # Bot started speaking → close gate
        if isinstance(frame, BotStartedSpeakingFrame):
            if self._enabled:
                if self._echo_tail_task and not self._echo_tail_task.done():
                    self._echo_tail_task.cancel()
                    self._echo_tail_task = None
                if not self._gate_closed:
                    self._gate_closed = True
                    self._gate_closed_at = time.monotonic()
                    self._frames_silenced = 0
            await self.push_frame(frame, direction)
            return

        # Bot stopped speaking → schedule gate opening after echo tail
        if isinstance(frame, BotStoppedSpeakingFrame):
            if self._enabled and self._gate_closed:
                if self._echo_tail_task and not self._echo_tail_task.done():
                    self._echo_tail_task.cancel()
                self._echo_tail_task = asyncio.create_task(self._open_after_tail())
            await self.push_frame(frame, direction)
            return

        # Gate incoming audio while closed
        if isinstance(frame, InputAudioRawFrame) and self._enabled and self._gate_closed:
            # Safety valve: force open after 30s
            if self._gate_closed_at and (time.monotonic() - self._gate_closed_at) > self._safety_limit_s:
                self._open_gate("safety_valve")
                await self.push_frame(frame, direction)
                return

            self._frames_silenced += 1
            self._total_silenced += 1
            silent = InputAudioRawFrame(
                audio=b"\x00" * len(frame.audio),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
            await self.push_frame(silent, direction)
            return

        await self.push_frame(frame, direction)

    async def _open_after_tail(self):
        """Wait for echo tail delay, then open gate."""
        try:
            await asyncio.sleep(self._echo_tail_s)
            self._open_gate("echo_tail_expired")
        except asyncio.CancelledError:
            pass  # New BotStartedSpeaking cancelled this — gate stays closed

    def _open_gate(self, reason: str):
        self._gate_closed = False
        logger.info(
            "echo_gate_opened",
            call_sid=self._call_sid,
            reason=reason,
            silenced_frames=self._frames_silenced,
            total_silenced=self._total_silenced,
        )


class HelloGuard(FrameProcessor):
    """Suppress 'hello?' utterances that cause response restart cascades.

    When the bot is processing (LLM thinking) or speaking, the user may
    say "Hello?" because they hear silence or audio breakage. This gets
    transcribed and either:
      - Interrupts the bot's current speech (cancels audio)
      - Pushes "Hello?" to context, restarting the LLM response

    Each restart adds 1-2s, so 2-3 "Hello?" = 4-6s perceived latency.

    This guard drops "hello?"-like transcripts (and their associated
    UserStoppedSpeakingFrame) during the processing and speaking windows,
    letting the original response complete uninterrupted.
    """

    _HELLO_WORDS = frozenset({"hello", "hallo", "hi", "hey", "alo", "helo"})

    def __init__(self, call_sid: str = "", **kwargs):
        super().__init__(name="HelloGuard", **kwargs)
        self._call_sid = call_sid
        self._bot_speaking = False
        self._pending_llm = False  # True after real transcript sent, cleared on BotStartedSpeaking
        self._suppressed_hello = False

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
            StartFrame,
            TranscriptionFrame,
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        # Bot started speaking — LLM responded, pipeline no longer idle
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._pending_llm = False
            self._suppressed_hello = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            await self.push_frame(frame, direction)
            return

        # New user speech turn — clear any stale echo suppression flag
        if isinstance(frame, UserStartedSpeakingFrame):
            if self._suppressed_hello:
                logger.info(
                    "hello_guard_reset_on_new_turn",
                    call_sid=self._call_sid,
                )
            self._suppressed_hello = False
            await self.push_frame(frame, direction)
            return

        # User stopped speaking
        if isinstance(frame, UserStoppedSpeakingFrame):
            if self._suppressed_hello:
                # Only "hello?" was captured — drop this to prevent
                # push_aggregation with "hello?" text
                self._suppressed_hello = False
                logger.debug(
                    "hello_guard_drop_stop",
                    call_sid=self._call_sid,
                )
                return
            await self.push_frame(frame, direction)
            return

        # Only suppress "hello?" when the pipeline is busy:
        #   - _bot_speaking: bot is actively outputting audio
        #   - _pending_llm: real transcript was sent, waiting for bot to start speaking
        # When pipeline is idle (bot finished speaking, no pending LLM),
        # "Hello" is a legitimate new turn — always let it through.
        if isinstance(frame, TranscriptionFrame):
            logger.info(
                "hello_guard_transcript",
                call_sid=self._call_sid,
                text=frame.text,
                bot_speaking=self._bot_speaking,
                pending_llm=self._pending_llm,
            )
            if self._bot_speaking or self._pending_llm:
                cleaned = frame.text.strip().lower().rstrip("?.!,;: ")
                words = cleaned.split()
                if (
                    words
                    and len(words) <= 2
                    and all(w in self._HELLO_WORDS for w in words)
                ):
                    self._suppressed_hello = True
                    logger.info(
                        "hello_guard_suppressed",
                        call_sid=self._call_sid,
                        text=frame.text,
                    )
                    return
            # Real (non-hello) transcript passed through — LLM will process it
            self._suppressed_hello = False
            self._pending_llm = True
            logger.info(
                "hello_guard_passed",
                call_sid=self._call_sid,
                text=frame.text,
            )

        await self.push_frame(frame, direction)


class TTSAudioLogger(FrameProcessor):
    """Logs TTS audio frames and saves raw PCM to disk for diagnostics."""

    def __init__(self, call_sid="", save_audio=True, **kwargs):
        super().__init__(name="TTSAudioLogger", **kwargs)
        self._call_sid = call_sid
        self._frame_count = 0
        self._save_audio = save_audio
        self._audio_file = None
        self._sample_rate = None
        self._total_bytes = 0

    def _ensure_file(self, sample_rate: int):
        if self._audio_file is None:
            import os
            dump_dir = "/tmp/tts_dumps"
            os.makedirs(dump_dir, exist_ok=True)
            safe_sid = self._call_sid.replace("/", "_")[:40]
            self._audio_file = open(f"{dump_dir}/{safe_sid}.raw", "wb")
            self._sample_rate = sample_rate
            logger.info("tts_dump_started", call_sid=self._call_sid,
                        path=f"{dump_dir}/{safe_sid}.raw", sample_rate=sample_rate)

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import EndFrame, StartFrame, TTSAudioRawFrame
        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, EndFrame):
            self._close_file()
        if isinstance(frame, TTSAudioRawFrame):
            self._frame_count += 1
            # Save raw PCM to file
            if self._save_audio and frame.audio:
                self._ensure_file(frame.sample_rate)
                self._audio_file.write(frame.audio)
                self._total_bytes += len(frame.audio)
            if self._frame_count <= 3 or self._frame_count % 50 == 0:
                import numpy as np
                audio_np = np.frombuffer(frame.audio, dtype=np.int16)
                rms = float(np.sqrt(np.mean(audio_np.astype(np.float64) ** 2)))
                max_amp = int(np.abs(audio_np).max()) if len(audio_np) > 0 else 0
                duration_ms = len(audio_np) / frame.sample_rate * 1000
                logger.info(
                    "tts_audio_frame",
                    call_sid=self._call_sid,
                    frame_num=self._frame_count,
                    sample_rate=frame.sample_rate,
                    audio_bytes=len(frame.audio),
                    duration_ms=round(duration_ms, 1),
                    rms=round(rms, 1),
                    max_amp=max_amp,
                    total_dumped=self._total_bytes,
                )
        await self.push_frame(frame, direction)

    def _close_file(self):
        if self._audio_file:
            self._audio_file.close()
            duration_s = self._total_bytes / (self._sample_rate * 2) if self._sample_rate else 0
            logger.info("tts_dump_finished", call_sid=self._call_sid,
                        total_bytes=self._total_bytes, duration_s=round(duration_s, 1))
            self._audio_file = None


class TTSTailTrim(FrameProcessor):
    """Drops pathological low-energy TTS tails before they reach telephony output.

    Sarvam occasionally emits a long near-silent/noisy tail after the spoken
    content has finished. Buffering a short run of low-energy frames lets us
    distinguish normal quiet phonemes from a real trailing artifact.
    """

    def __init__(self, call_sid: str = "", **kwargs):
        super().__init__(name="TTSTailTrim", **kwargs)
        self._call_sid = call_sid
        self._speech_ms = 0.0
        self._pending_tail: list = []
        self._pending_tail_ms = 0.0
        self._dropping_tail = False
        self._dropped_frames = 0
        self._dropped_ms = 0.0

    def _reset(self):
        self._speech_ms = 0.0
        self._pending_tail.clear()
        self._pending_tail_ms = 0.0
        self._dropping_tail = False
        self._dropped_frames = 0
        self._dropped_ms = 0.0

    async def _flush_pending_tail(self, direction: FrameDirection):
        while self._pending_tail:
            pending = self._pending_tail.pop(0)
            await self.push_frame(pending, direction)
        self._pending_tail_ms = 0.0

    @staticmethod
    def _frame_metrics(frame) -> tuple[float, int, float]:
        import numpy as np

        audio_np = np.frombuffer(frame.audio, dtype=np.int16)
        if len(audio_np) == 0:
            return 0.0, 0, 0.0
        rms = float(np.sqrt(np.mean(audio_np.astype(np.float64) ** 2)))
        max_amp = int(np.abs(audio_np).max())
        channels = max(int(getattr(frame, "num_channels", 1) or 1), 1)
        duration_ms = len(frame.audio) / (frame.sample_rate * 2 * channels) * 1000
        return rms, max_amp, duration_ms

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import EndFrame, StartFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, EndFrame):
            self._reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSStartedFrame):
            self._reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSStoppedFrame):
            if self._pending_tail:
                self._dropped_frames += len(self._pending_tail)
                self._dropped_ms += self._pending_tail_ms
                logger.info(
                    "tts_tail_trimmed",
                    call_sid=self._call_sid,
                    frames=self._dropped_frames,
                    dropped_ms=round(self._dropped_ms, 1),
                    speech_ms=round(self._speech_ms, 1),
                    reason="tts_stopped_with_low_energy_tail",
                )
                self._pending_tail.clear()
                self._pending_tail_ms = 0.0
            self._dropping_tail = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSAudioRawFrame):
            rms, max_amp, duration_ms = self._frame_metrics(frame)
            is_low_energy = rms < 90.0 and max_amp < 300
            tail_trim_eligible = self._speech_ms >= 800.0

            if not is_low_energy or not tail_trim_eligible:
                if self._pending_tail:
                    await self._flush_pending_tail(direction)
                self._dropping_tail = False
                self._speech_ms += duration_ms
                await self.push_frame(frame, direction)
                return

            if self._dropping_tail:
                self._dropped_frames += 1
                self._dropped_ms += duration_ms
                return

            self._pending_tail.append(frame)
            self._pending_tail_ms += duration_ms
            if self._pending_tail_ms >= 900.0:
                self._dropped_frames += len(self._pending_tail)
                self._dropped_ms += self._pending_tail_ms
                logger.info(
                    "tts_tail_trimmed",
                    call_sid=self._call_sid,
                    frames=self._dropped_frames,
                    dropped_ms=round(self._dropped_ms, 1),
                    speech_ms=round(self._speech_ms, 1),
                    reason="low_energy_tail_detected",
                    rms=round(rms, 1),
                    max_amp=max_amp,
                )
                self._pending_tail.clear()
                self._pending_tail_ms = 0.0
                self._dropping_tail = True
            return

        if self._pending_tail:
            await self._flush_pending_tail(direction)
        await self.push_frame(frame, direction)


class LatencyTracker(FrameProcessor):
    """Pass-through processor that logs timestamps and computes latency deltas.

    Inserted at key pipeline positions to measure per-stage latency.
    Passes ALL frames through unconditionally.

    post_stt position computes:
      - stt_latency_ms: UserStoppedSpeaking → TranscriptionFrame

    post_tts position computes:
      - llm_ttfb_ms: UserStoppedSpeaking → LLMFullResponseStartFrame
      - tts_ttfb_ms: LLMFullResponseStart → TTSAudioRawFrame
      - e2e_latency_ms: UserStoppedSpeaking → BotStartedSpeakingFrame

    Also detects echo: logs any TranscriptionFrame arriving while bot is speaking.
    """

    # Import frame types lazily to avoid circular imports at module level.
    _frame_types: dict | None = None

    @classmethod
    def _load_frame_types(cls):
        if cls._frame_types is not None:
            return
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
            LLMFullResponseStartFrame,
            LLMTextFrame,
            TTSAudioRawFrame,
            TTSStartedFrame,
            TranscriptionFrame,
            UserStoppedSpeakingFrame,
        )
        cls._frame_types = {
            "user_stopped_speaking": UserStoppedSpeakingFrame,
            "stt_transcript": TranscriptionFrame,
            "llm_response_start": LLMFullResponseStartFrame,
            "llm_first_token": LLMTextFrame,
            "tts_started": TTSStartedFrame,
            "tts_first_audio": TTSAudioRawFrame,
            "bot_started_speaking": BotStartedSpeakingFrame,
        }
        cls._bot_stopped_type = BotStoppedSpeakingFrame

    def __init__(self, position: str, call_sid: str, **kwargs):
        super().__init__(name=f"LatencyTracker-{position}", **kwargs)
        self._position = position
        self._call_sid = call_sid
        self._turn_id = 0
        self._seen_this_turn: set[str] = set()
        self._load_frame_types()

        # Delta computation timestamps (per-turn, reset on UserStoppedSpeaking)
        self._user_stopped_ts: float | None = None
        self._llm_start_ts: float | None = None

        # Echo detection: track bot speaking state via upstream frames
        self._bot_is_speaking = False

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame,
            StartFrame,
            TranscriptionFrame,
            UserStoppedSpeakingFrame,
        )

        # Must handle StartFrame to initialize, then push it downstream.
        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        # Track bot speaking state for echo detection (upstream SystemFrames)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_is_speaking = True
        elif isinstance(frame, self._bot_stopped_type):
            self._bot_is_speaking = False

        now = time.monotonic()

        # Reset tracking on new turn.
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._turn_id += 1
            self._seen_this_turn = set()
            self._user_stopped_ts = now
            self._llm_start_ts = None

        # Echo detection: log transcripts arriving while bot is speaking
        if (
            isinstance(frame, TranscriptionFrame)
            and self._bot_is_speaking
            and self._position == "post_stt"
        ):
            _timing_logger.warning(
                "echo_transcript_during_bot_speech",
                call_sid=self._call_sid,
                turn=self._turn_id,
                text=frame.text[:100] if frame.text else "",
                ts=now,
            )

        # Log first occurrence of each tracked frame type per turn + compute deltas.
        for label, frame_type in self._frame_types.items():
            if isinstance(frame, frame_type) and label not in self._seen_this_turn:
                self._seen_this_turn.add(label)
                _timing_logger.info(
                    "latency_event",
                    position=self._position,
                    stage=label,
                    turn=self._turn_id,
                    call_sid=self._call_sid,
                    ts=now,
                )

                # Compute deltas based on position
                if self._user_stopped_ts is not None:
                    if label == "stt_transcript" and self._position == "post_stt":
                        delta_ms = round((now - self._user_stopped_ts) * 1000)
                        _timing_logger.info(
                            "latency_delta",
                            metric="stt_latency_ms",
                            value_ms=delta_ms,
                            turn=self._turn_id,
                            call_sid=self._call_sid,
                        )

                    elif label == "llm_response_start" and self._position == "post_tts":
                        delta_ms = round((now - self._user_stopped_ts) * 1000)
                        self._llm_start_ts = now
                        _timing_logger.info(
                            "latency_delta",
                            metric="llm_ttfb_ms",
                            value_ms=delta_ms,
                            turn=self._turn_id,
                            call_sid=self._call_sid,
                        )

                    elif label == "tts_first_audio" and self._position == "post_tts":
                        if self._llm_start_ts is not None:
                            tts_delta = round((now - self._llm_start_ts) * 1000)
                            _timing_logger.info(
                                "latency_delta",
                                metric="tts_ttfb_ms",
                                value_ms=tts_delta,
                                turn=self._turn_id,
                                call_sid=self._call_sid,
                            )

                    elif label == "bot_started_speaking" and self._position == "post_tts":
                        e2e_ms = round((now - self._user_stopped_ts) * 1000)
                        _timing_logger.info(
                            "latency_delta",
                            metric="e2e_latency_ms",
                            value_ms=e2e_ms,
                            turn=self._turn_id,
                            call_sid=self._call_sid,
                        )

                break

        await self.push_frame(frame, direction)


def _get_gemini_tts_class():
    """Return a GeminiTTSService subclass with 100ms chunk buffering.

    Imported lazily to avoid pulling in google TTS at module load.
    """
    from pipecat.services.google.tts import GeminiTTSService

    class SmallChunkGeminiTTS(GeminiTTSService):
        """GeminiTTSService with 100ms chunk buffering instead of 500ms.

        Reduces inter-sentence audio gaps and smooths frame delivery to Plivo.
        """

        @property
        def chunk_size(self) -> int:
            return int(self.sample_rate * 0.1 * 2)  # 100ms, 2 bytes/sample

    return SmallChunkGeminiTTS


def _build_workflow_tools(bot_config: BotConfig, call_context: CallContext):
    """Build LLM tool definitions and handler for during-call CRM workflows."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    workflows = getattr(bot_config, "ghl_workflows", None) or []
    if isinstance(workflows, str):
        import json
        try:
            workflows = json.loads(workflows)
        except (json.JSONDecodeError, TypeError):
            workflows = []
    during_call = [
        wf for wf in workflows
        if isinstance(wf, dict) and wf.get("timing") == "during_call" and wf.get("enabled") and wf.get("tag")
    ]

    if not during_call:
        return None, None

    # Ensure each workflow has an id
    for i, wf in enumerate(during_call):
        if "id" not in wf:
            wf["id"] = f"wf_{i}"

    wf_descriptions = "\n".join(
        f"- {wf['id']}: {wf.get('name', 'Unnamed')} — "
        f"{wf.get('trigger_description', 'Tag: ' + wf['tag'])}"
        for wf in during_call
    )

    tool_schema = FunctionSchema(
        name="trigger_crm_workflow",
        description=(
            "Trigger a CRM workflow to tag the contact. "
            "Use this when the conversation matches a workflow's trigger condition.\n\n"
            f"Available workflows:\n{wf_descriptions}"
        ),
        properties={
            "workflow_id": {
                "type": "string",
                "description": "The ID of the workflow to trigger",
                "enum": [wf["id"] for wf in during_call],
            }
        },
        required=["workflow_id"],
    )

    wf_lookup = {wf["id"]: wf for wf in during_call}

    async def handle_trigger_workflow(params):
        wf_id = params.arguments.get("workflow_id")
        wf = wf_lookup.get(wf_id)
        if not wf:
            await params.result_callback(f"Unknown workflow: {wf_id}")
            return

        api_key = getattr(bot_config, "ghl_api_key", None)
        location_id = getattr(bot_config, "ghl_location_id", None)
        if not api_key or not location_id:
            await params.result_callback("CRM not configured")
            return

        # Return immediately so LLM can continue generating text without
        # waiting for the GHL HTTP round-trip (~1-2s).
        tag = wf["tag"]
        await params.result_callback(f"Done — tagged contact with '{tag}'")

        import asyncio

        async def _tag_in_background():
            contact_id = call_context.ghl_contact_id
            if not contact_id:
                from app.database import get_db_session
                from app.ghl.client import GHLClient
                from app.models.call_log import CallLog
                from sqlalchemy import select

                ghl = GHLClient(api_key=api_key)
                try:
                    async with get_db_session() as db:
                        result = await db.execute(
                            select(CallLog).where(CallLog.call_sid == call_context.call_sid)
                        )
                        call_log = result.scalar_one_or_none()
                    phone = call_log.contact_phone if call_log else None
                    if phone:
                        contact_id = await ghl.find_contact(location_id, phone)
                finally:
                    await ghl.close()

            if not contact_id:
                logger.warning("workflow_skip_no_contact", call_sid=call_context.call_sid, tag=tag)
                return

            from app.ghl.client import GHLClient

            ghl = GHLClient(api_key=api_key)
            try:
                ok = await ghl.tag_contact(contact_id, tag)
                logger.info(
                    "during_call_workflow_triggered",
                    call_sid=call_context.call_sid,
                    workflow=wf.get("name"),
                    tag=tag,
                    success=ok,
                )
            except Exception as e:
                logger.error(
                    "during_call_workflow_failed",
                    call_sid=call_context.call_sid,
                    tag=tag,
                    error=str(e),
                )
            finally:
                await ghl.close()

        asyncio.create_task(_tag_in_background())

    return tool_schema, handle_trigger_workflow


def _build_callback_tool(bot_config: BotConfig, call_context: CallContext):
    """Build LLM tool for scheduling callbacks."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    if not getattr(bot_config, "callback_enabled", False):
        return None, None

    max_retries = getattr(bot_config, "callback_max_retries", 3)

    tool_schema = FunctionSchema(
        name="schedule_callback",
        description=(
            "Schedule a callback to this contact. Use this when the person asks to be called back later, "
            "says they are busy, or requests a call at a different time.\n\n"
            "IMPORTANT: Before calling this, try to ask the person when they'd like to be called back. "
            "If they give a time, pass it as callback_time. If they don't want to specify, leave it empty.\n\n"
            f"Maximum {max_retries} callback attempts are allowed per contact."
        ),
        properties={
            "callback_time": {
                "type": "string",
                "description": (
                    "When the person wants to be called back, e.g. '3 PM', 'tomorrow morning', "
                    "'in 2 hours', 'after 30 minutes'. Leave empty if they didn't specify a time."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Why the callback is being scheduled, e.g. 'customer is busy', 'requested afternoon call'",
            },
        },
        required=["reason"],
    )

    async def handle_schedule_callback(params):
        callback_time = params.arguments.get("callback_time")
        reason = params.arguments.get("reason", "callback requested")

        # Determine retry count from the queue entry that spawned this call
        current_retry = 0
        try:
            from app.database import get_db_session
            from app.models.call_log import CallLog
            from app.models.call_queue import QueuedCall
            from sqlalchemy import select

            async with get_db_session() as db:
                log_result = await db.execute(
                    select(CallLog).where(CallLog.call_sid == call_context.call_sid)
                )
                call_log = log_result.scalar_one_or_none()
                if call_log:
                    q_result = await db.execute(
                        select(QueuedCall).where(QueuedCall.call_log_id == call_log.id)
                    )
                    spawning_queue = q_result.scalar_one_or_none()
                    if spawning_queue:
                        current_retry = spawning_queue.retry_count
        except Exception as e:
            logger.error("callback_retry_count_lookup_failed", error=str(e))

        next_retry = current_retry + 1

        if next_retry > max_retries:
            await params.result_callback(
                f"Cannot schedule callback — maximum of {max_retries} callback attempts reached. "
                "Apologize to the customer and let them know someone will reach out."
            )
            return

        # Schedule the callback
        try:
            from app.database import get_db_session
            from app.services.callback_scheduler import create_scheduled_callback
            from app.models.call_log import CallLog
            from sqlalchemy import select

            async with get_db_session() as db:
                log_result = await db.execute(
                    select(CallLog).where(CallLog.call_sid == call_context.call_sid)
                )
                call_log = log_result.scalar_one_or_none()

                await create_scheduled_callback(
                    db,
                    org_id=bot_config.org_id,
                    bot_id=bot_config.id,
                    contact_name=call_context.contact_name,
                    contact_phone=call_log.contact_phone if call_log else "",
                    ghl_contact_id=call_context.ghl_contact_id,
                    call_sid=call_context.call_sid,
                    callback_time=callback_time,
                    reason=reason,
                    retry_count=next_retry,
                    tz_name=getattr(bot_config, "callback_timezone", "Asia/Kolkata"),
                    default_delay_hours=getattr(bot_config, "callback_retry_delay_hours", 2.0),
                    window_start=getattr(bot_config, "callback_window_start", 9),
                    window_end=getattr(bot_config, "callback_window_end", 20),
                )
                await db.commit()

            time_msg = callback_time if callback_time else "the next available time"
            await params.result_callback(
                f"Callback scheduled for {time_msg}. Now end the call politely."
            )

            logger.info(
                "callback_tool_invoked",
                call_sid=call_context.call_sid,
                callback_time=callback_time,
                reason=reason,
                retry=next_retry,
            )
        except Exception as e:
            logger.error("callback_schedule_failed", call_sid=call_context.call_sid, error=str(e))
            await params.result_callback(
                "I couldn't schedule the callback due to a technical issue. "
                "Apologize and let them know someone will call back."
            )

    return tool_schema, handle_schedule_callback


def _build_switch_bot_tool(bot_config: BotConfig, call_context: CallContext):
    """Build LLM tool for switching to a different bot mid-call."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    targets = getattr(bot_config, "bot_switch_targets", None) or []
    if isinstance(targets, str):
        import json
        try:
            targets = json.loads(targets)
        except (json.JSONDecodeError, TypeError):
            targets = []

    if not targets:
        return None, None

    target_descriptions = "\n".join(
        f"- {t['id']}: {t.get('description', 'No description')}"
        for t in targets
    )

    tool_schema = FunctionSchema(
        name="switch_bot",
        description=(
            "Transfer this call to a different agent. The current call will end and the other agent "
            "will call the customer immediately.\n\n"
            "Use this when the customer needs a different language or agent type.\n\n"
            f"Available targets:\n{target_descriptions}"
        ),
        properties={
            "target_id": {
                "type": "string",
                "description": "The ID of the target agent to switch to",
                "enum": [t["id"] for t in targets],
            },
            "reason": {
                "type": "string",
                "description": "Why the switch is happening, e.g. 'customer prefers Hindi'",
            },
        },
        required=["target_id", "reason"],
    )

    target_lookup = {t["id"]: t for t in targets}

    async def handle_switch_bot(params):
        target_id = params.arguments.get("target_id")
        reason = params.arguments.get("reason", "bot switch requested")

        target = target_lookup.get(target_id)
        if not target:
            await params.result_callback(f"Unknown target: {target_id}")
            return

        target_bot_id = target.get("target_bot_id")
        if not target_bot_id:
            await params.result_callback("Target bot not configured properly.")
            return

        try:
            from app.database import get_db_session
            from app.models.call_log import CallLog
            from app.models.call_queue import QueuedCall
            from sqlalchemy import select

            async with get_db_session() as db:
                # Get current call's contact phone
                log_result = await db.execute(
                    select(CallLog).where(CallLog.call_sid == call_context.call_sid)
                )
                call_log = log_result.scalar_one_or_none()
                contact_phone = call_log.contact_phone if call_log else ""

                # Create queue entry for target bot with 2min delay
                # so the current call fully ends before the new bot calls
                from datetime import datetime, timedelta, timezone as tz
                switch_delay = datetime.now(tz.utc) + timedelta(minutes=2)

                queued_call = QueuedCall(
                    org_id=bot_config.org_id,
                    bot_id=target_bot_id,
                    contact_name=call_context.contact_name,
                    contact_phone=contact_phone,
                    ghl_contact_id=call_context.ghl_contact_id,
                    source="bot_switch",
                    status="queued",
                    priority=2,
                    scheduled_at=switch_delay,
                    extra_vars={
                        "switched_from_bot": str(bot_config.id),
                        "switch_reason": reason,
                        "original_call_sid": call_context.call_sid,
                    },
                )
                db.add(queued_call)
                await db.commit()

            await params.result_callback(
                "Transfer initiated. Say a brief goodbye and then call end_call immediately."
            )

            logger.info(
                "bot_switch_initiated",
                call_sid=call_context.call_sid,
                from_bot=str(bot_config.id),
                to_bot=target_bot_id,
                reason=reason,
            )
        except Exception as e:
            logger.error("bot_switch_failed", call_sid=call_context.call_sid, error=str(e))
            await params.result_callback(
                "I couldn't transfer the call due to a technical issue. Continue helping the customer."
            )

    return tool_schema, handle_switch_bot


def _build_end_call_tool():
    """Build the end_call LLM tool definition as a provider-agnostic FunctionSchema."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    return FunctionSchema(
        name="end_call",
        description=(
            "End the phone call. Call this ONLY when:\n"
            "1) Both you AND the customer have exchanged EXPLICIT goodbye words "
            "(bye/goodbye/take care/see you) — call end_call with NO additional text.\n"
            "2) The customer says 'not interested', 'don't call me', 'wrong number', or any clear rejection "
            "after you've attempted to address their concern.\n"
            "3) The customer explicitly asks to hang up or end the call.\n\n"
            "IMPORTANT: If you already said goodbye and the customer responds with "
            "'bye'/'okay bye'/'thanks bye', call end_call IMMEDIATELY without saying anything else. "
            "Do NOT say goodbye twice.\n\n"
            "NEVER end the call if:\n"
            "- The customer only said 'yeah', 'yes', 'okay', 'thank you', 'good', 'fine', 'hmm', or any short acknowledgment — "
            "these are NOT signs of disinterest. Many Indian users give brief replies but are still engaged. Continue the conversation.\n"
            "- The customer is giving one-word or short answers — this is normal phone behavior, NOT rejection. "
            "Keep asking questions and progressing through your flow.\n"
            "- The customer is still mid-sentence, stuttering, or starting a new question.\n"
            "- The customer is hesitant but has NOT explicitly said goodbye or rejected.\n"
            "- You are unsure whether the customer wants to end — keep the conversation going instead.\n"
            "- You have NOT completed your full conversation flow — finish all required steps first."
        ),
        properties={
            "reason": {
                "type": "string",
                "description": "Brief reason for ending the call (e.g., 'mutual_goodbye', 'not_interested', 'wrong_number')",
            }
        },
        required=["reason"],
    )


async def build_pipeline(
    bot_config: BotConfig,
    call_context: CallContext,
    websocket: WebSocket,
    provider: str = "plivo",
    stream_sid: str = "",
    plivo_stream_id: str = "",
    greeting_text: str = "",
) -> tuple[PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext, CallGuard]:
    """
    Construct an isolated Pipecat pipeline for a single call.

    Args:
        bot_config: Loaded from DB — contains voice, timeouts, credentials.
        call_context: Per-call data — filled prompt, contact info, call_sid.
        websocket: The accepted FastAPI WebSocket connection from Plivo/Twilio.
        provider: "plivo" or "twilio" — determines serializer and audio format.
        plivo_stream_id: Pre-captured Plivo stream ID from start event (Phase 3).
            If provided, serializer skips waiting for start event.

    Returns:
        (task, transport, context, call_guard).
    """

    # --- Serializer (provider-specific) ---
    if provider == "twilio":
        from pipecat.serializers.twilio import TwilioFrameSerializer

        serializer = TwilioFrameSerializer(
            stream_sid=stream_sid,
            params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
        )
    else:
        serializer = PlivoPCMFrameSerializer(
            stream_id=call_context.call_sid,
            plivo_stream_id=plivo_stream_id,
        )

    # --- Transport ---
    # VAD and turn analyzer go on transport params in pipecat 0.0.104.
    # Sarvam STT has server-side VAD (vad_signals=True) so we skip local
    # Silero VAD to avoid double-interrupt cascades that kill in-flight LLM/TTS.
    stt_language = getattr(call_context, "language", "en-IN") or "en-IN"
    stt_provider = getattr(bot_config, "stt_provider", "deepgram") or "deepgram"

    if stt_provider == "sarvam":
        # Sarvam has server-side VAD (vad_signals=True, high_vad_sensitivity=True).
        # Local SileroVAD is needed so the pipeline knows when the user speaks,
        # but we do NOT flush Sarvam on vad_stopped (see _SafeSarvamSTT) to avoid
        # hallucinated transcripts from short utterance fragments.
        # SmartTurn prevents premature interruptions by predicting if user is done.
        # stop_secs=1.0 gives SmartTurn's INCOMPLETE verdict time to hold —
        # Sarvam fragments speech into tiny segments, so 0.3s was overriding
        # SmartTurn and forcing turn completion on every fragment.
        transport_params = FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=16000,
            audio_out_10ms_chunks=10,
            add_wav_header=False,
            serializer=serializer,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                stop_secs=0.5,
                min_volume=0.5,
            )),
            turn_analyzer=LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(stop_secs=1.0),
            ),
        )
    elif stt_provider == "smallest":
        # Smallest Pulse: use local Silero VAD + SmartTurn
        transport_params = FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=16000,
            audio_out_10ms_chunks=10,
            add_wav_header=False,
            serializer=serializer,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                stop_secs=0.5,
                min_volume=0.5,
            )),
            turn_analyzer=LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(stop_secs=1.0),
            ),
        )
    else:
        # Deepgram: use local Silero VAD + SmartTurn for turn detection.
        transport_params = FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=16000,
            audio_out_10ms_chunks=10,
            add_wav_header=False,
            serializer=serializer,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                stop_secs=0.5,
                min_volume=0.5,
            )),
            turn_analyzer=LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(stop_secs=1.0),
            ),
        )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=transport_params,
    )

    if stt_provider == "sarvam":
        from pipecat.services.sarvam.stt import SarvamSTTService
        from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame
        from pipecat.transcriptions.language import Language as PipecatLanguage

        class _SafeSarvamSTT(SarvamSTTService):
            """Sarvam STT with two critical fixes:

            1. No broadcast_interruption on START_SPEECH — prevents cascade
               cancellations that kill in-flight LLM/TTS.

            2. Buffered END_SPEECH — Sarvam sends END_SPEECH *before* the
               transcript data message. If we broadcast UserStoppedSpeakingFrame
               immediately, the context aggregator sees empty _aggregation and
               doesn't push to LLM. The transcript arrives later but nothing
               triggers push_aggregation. Fix: buffer the stop frame and emit
               it AFTER the transcript data arrives.
            """

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._end_speech_pending = False
                self._end_speech_timeout_task: asyncio.Task | None = None
                self._audio_frames_sent = 0
                self._last_audio_log_time = 0.0
                self._call_sid_tag = ""  # Set after pipeline starts

            async def _update_settings(self, delta):
                """Apply language changes by disconnecting and reconnecting to Sarvam."""
                from pipecat.services.settings import is_given
                if is_given(getattr(delta, 'language', None)) and delta.language is not None:
                    self._settings.language = delta.language
                    logger.info(
                        "sarvam_stt_language_switch",
                        call_sid=self._call_sid_tag,
                        new_language=str(delta.language),
                    )
                    await self._disconnect()
                    await self._connect()
                    return {"language": delta.language}
                return await super()._update_settings(delta)

            async def process_frame(self, frame, direction: FrameDirection):
                from pipecat.frames.frames import (
                    InputAudioRawFrame,
                    StartFrame,
                    VADUserStartedSpeakingFrame,
                    VADUserStoppedSpeakingFrame,
                )
                # Count audio frames reaching Sarvam STT
                if isinstance(frame, InputAudioRawFrame):
                    self._audio_frames_sent += 1
                    now = time.monotonic()
                    # Log every 5 seconds
                    if now - self._last_audio_log_time >= 5.0:
                        # Check if audio is silent (all zeros)
                        is_silent = frame.audio == b"\x00" * len(frame.audio)
                        logger.info(
                            "sarvam_stt_audio_stats",
                            call_sid=self._call_sid_tag,
                            frames_total=self._audio_frames_sent,
                            latest_frame_bytes=len(frame.audio),
                            is_silent=is_silent,
                            end_speech_pending=self._end_speech_pending,
                        )
                        self._last_audio_log_time = now

                # When using Pipecat VAD (vad_signals=False), Silero sends
                # VADUserStoppedSpeakingFrame. The base class pushes this downstream
                # AND calls flush(). But the frame reaches the aggregator BEFORE
                # flush returns the transcript — same race condition as Sarvam's
                # END_SPEECH. Fix: intercept, buffer, flush, emit after transcript.
                if isinstance(frame, VADUserStoppedSpeakingFrame):
                    logger.info(
                        "sarvam_stt_vad_stopped",
                        call_sid=self._call_sid_tag,
                        end_speech_pending=self._end_speech_pending,
                    )
                    self._end_speech_pending = True
                    if self._end_speech_timeout_task:
                        self._end_speech_timeout_task.cancel()
                    self._end_speech_timeout_task = asyncio.create_task(
                        self._end_speech_timeout()
                    )
                    # Flush Sarvam to finalize transcript
                    if self._socket_client:
                        try:
                            await self._socket_client.flush()
                        except Exception as e:
                            logger.warning(
                                "sarvam_stt_flush_error",
                                call_sid=self._call_sid_tag,
                                error=str(e),
                            )
                    # Don't call super — prevents frame from reaching aggregator
                    # before transcript. Also skip base class's redundant flush().
                    return

                # Let VADUserStartedSpeakingFrame through and start metrics
                if isinstance(frame, VADUserStartedSpeakingFrame):
                    await self._start_metrics()

                await super().process_frame(frame, direction)

            async def _handle_message(self, message):
                try:
                    logger.info(
                        "sarvam_stt_ws_message",
                        call_sid=self._call_sid_tag,
                        msg_type=message.type,
                        detail=str(message.data)[:200] if hasattr(message, 'data') else "no_data",
                    )
                    if message.type == "events":
                        signal = message.data.signal_type
                        if signal == "START_SPEECH":
                            logger.info("sarvam_stt_start_speech",
                                        call_sid=self._call_sid_tag,
                                        audio_frames_so_far=self._audio_frames_sent)
                            await self._start_metrics()
                            await self._call_event_handler("on_speech_started")
                            await self.broadcast_frame(UserStartedSpeakingFrame)
                            logger.info("sarvam_stt_broadcast_user_started",
                                        call_sid=self._call_sid_tag)
                            # NOTE: no broadcast_interruption() — let pipeline strategy decide
                        elif signal == "END_SPEECH":
                            logger.info("sarvam_stt_end_speech",
                                        call_sid=self._call_sid_tag,
                                        pending_before=self._end_speech_pending)
                            await self._call_event_handler("on_speech_stopped")
                            # Buffer stop frame — wait for transcript before broadcasting
                            self._end_speech_pending = True
                            # Safety timeout: if transcript never arrives, send stop frame anyway
                            if self._end_speech_timeout_task:
                                self._end_speech_timeout_task.cancel()
                            self._end_speech_timeout_task = asyncio.create_task(
                                self._end_speech_timeout()
                            )
                        else:
                            logger.warning("sarvam_stt_unknown_signal",
                                           call_sid=self._call_sid_tag,
                                           signal=signal)
                    elif message.type == "data":
                        transcript = getattr(message.data, 'transcript', None)
                        lang_code = getattr(message.data, 'language_code', None)
                        # Check audio duration from Sarvam metrics to filter hallucinations
                        audio_dur = getattr(getattr(message.data, 'metrics', None), 'audio_duration', None)
                        logger.info("sarvam_stt_transcript_received",
                                    call_sid=self._call_sid_tag,
                                    transcript=transcript,
                                    language_code=lang_code,
                                    audio_duration=audio_dur,
                                    end_speech_pending=self._end_speech_pending)
                        # Cancel timeout — transcript arrived
                        if self._end_speech_timeout_task:
                            self._end_speech_timeout_task.cancel()
                            self._end_speech_timeout_task = None
                        # Drop likely-hallucinated transcripts from very short audio (<0.5s)
                        if audio_dur is not None and audio_dur < 0.5 and transcript:
                            logger.warning("sarvam_stt_short_audio_dropped",
                                           call_sid=self._call_sid_tag,
                                           transcript=transcript,
                                           audio_duration=audio_dur)
                            # Still clear pending state but don't emit transcript
                            if self._end_speech_pending:
                                self._end_speech_pending = False
                                await self.broadcast_frame(UserStoppedSpeakingFrame)
                        else:
                            # Process transcript first (creates TranscriptionFrame)
                            await super()._handle_message(message)
                            # NOW send the buffered stop frame so aggregator has the transcript
                            if self._end_speech_pending:
                                self._end_speech_pending = False
                                logger.info("sarvam_stt_broadcast_user_stopped_after_transcript",
                                            call_sid=self._call_sid_tag,
                                            transcript=transcript)
                                await self.broadcast_frame(UserStoppedSpeakingFrame)
                    else:
                        logger.warning("sarvam_stt_unknown_msg_type",
                                       call_sid=self._call_sid_tag,
                                       msg_type=message.type)
                except Exception as e:
                    logger.error("sarvam_stt_handle_error",
                                 call_sid=self._call_sid_tag,
                                 error=str(e),
                                 msg_type=getattr(message, 'type', 'unknown'))
                    await self.push_error(error_msg=f"Failed to handle message: {e}", exception=e)
                    await self.stop_all_metrics()

            async def _end_speech_timeout(self):
                """Safety: send UserStoppedSpeakingFrame if no transcript arrives within 2s."""
                try:
                    await asyncio.sleep(2.0)
                    if self._end_speech_pending:
                        self._end_speech_pending = False
                        logger.warning("sarvam_stt_end_speech_timeout",
                                       call_sid=self._call_sid_tag,
                                       detail="No transcript after END_SPEECH, sending stop frame")
                        await self.broadcast_frame(UserStoppedSpeakingFrame)
                except asyncio.CancelledError:
                    pass

        _SARVAM_LANG_MAP = {
            "hi-IN": PipecatLanguage.HI_IN,
            "bn-IN": PipecatLanguage.BN_IN,
            "gu-IN": PipecatLanguage.GU_IN,
            "kn-IN": PipecatLanguage.KN_IN,
            "ml-IN": PipecatLanguage.ML_IN,
            "mr-IN": PipecatLanguage.MR_IN,
            "ta-IN": PipecatLanguage.TA_IN,
            "te-IN": PipecatLanguage.TE_IN,
            "pa-IN": PipecatLanguage.PA_IN,
            "or-IN": PipecatLanguage.OR_IN,
            "as-IN": PipecatLanguage.AS_IN,
            "ur-IN": PipecatLanguage.UR_IN,
            "en-IN": PipecatLanguage.EN_IN,
        }
        # "unknown"/"multi" → language=None so Sarvam falls back to "unknown" (auto-detect)
        sarvam_lang = None if stt_language in ("unknown", "multi") else _SARVAM_LANG_MAP.get(stt_language, PipecatLanguage.EN_IN)

        stt = _SafeSarvamSTT(
            api_key=settings.SARVAM_API_KEY,
            model="saaras:v3",
            sample_rate=16000,
            input_audio_codec="wav",
            params=SarvamSTTService.InputParams(
                language=sarvam_lang,
                mode="translate",
                vad_signals=True,
                high_vad_sensitivity=True,
            ),
            keepalive_timeout=30.0,
        )
        stt._call_sid_tag = call_context.call_sid
        logger.info(
            "stt_provider_selected",
            provider="sarvam",
            model="saaras:v3",
            mode="transcribe",
            language=stt_language,
        )
    elif stt_provider == "smallest":
        from app.services.smallest_stt import SmallestSTTService
        # Pulse "multi" is unreliable — default to "en" for Indian English
        smallest_language = "en" if stt_language in ("unknown", "multi") else stt_language.split("-")[0]
        stt = SmallestSTTService(
            api_key=settings.SMALLEST_API_KEY,
            language=smallest_language,
            sample_rate=16000,
        )
        logger.info("stt_provider_selected", provider="smallest", model="pulse", language=smallest_language)
    else:
        # nova-3: "unknown" → "multi" (auto-detect), otherwise respect user's choice
        deepgram_language = "multi" if stt_language == "unknown" else stt_language
        stt = DeepgramSTTService(
            api_key=settings.DEEPGRAM_API_KEY,
            live_options=LiveOptions(
                model="nova-3",
                language=deepgram_language,
                interim_results=True,
                utterance_end_ms="1000",
                endpointing=100,
                punctuate=True,
                smart_format=True,
            ),
        )
        logger.info("stt_provider_selected", provider="deepgram", model="nova-3", language=deepgram_language)

    # --- LLM ---
    llm_provider = getattr(bot_config, "llm_provider", "google")

    if llm_provider == "groq":
        from pipecat.services.openai.base_llm import BaseOpenAILLMService
        from pipecat.services.groq.llm import GroqLLMService

        groq_model = getattr(bot_config, "llm_model", "llama-3.3-70b-versatile")
        # Reasoning models (gpt-oss) need reasoning_effort + max_completion_tokens;
        # standard models (llama) use plain max_tokens.
        if "gpt-oss" in groq_model:
            groq_params = BaseOpenAILLMService.InputParams(
                temperature=0.7,
                max_completion_tokens=1024,
                extra={"reasoning_effort": "low"},
            )
        else:
            groq_params = BaseOpenAILLMService.InputParams(
                temperature=0.7,
                max_tokens=1024,
            )

        llm = GroqLLMService(
            api_key=settings.GROQ_API_KEY,
            model=groq_model,
            params=groq_params,
        )
        logger.info("llm_provider_selected", provider="groq", model=groq_model)
    else:
        # Thinking toggle: when enabled, use dynamic budget (-1) so the model
        # decides how much to think.  When disabled, don't pass a thinking
        # config — Pipecat's default sets thinking_budget=0 for 2.5 Flash.
        from pipecat.services.google.llm import GoogleThinkingConfig

        thinking_enabled = getattr(bot_config, "llm_thinking_enabled", False)
        thinking_cfg = GoogleThinkingConfig(thinking_budget=-1) if thinking_enabled else None
        llm = GoogleVertexLLMService(
            credentials_path=settings.GOOGLE_APPLICATION_CREDENTIALS,
            project_id=settings.GOOGLE_CLOUD_PROJECT,
            location=settings.VERTEX_AI_LOCATION,
            model=getattr(bot_config, "llm_model", "gemini-2.5-flash"),
            params=GoogleLLMService.InputParams(
                temperature=0.7,
                max_tokens=256,
                thinking=thinking_cfg,
            ),
        )
        logger.info("llm_provider_selected", provider="google",
                     model=getattr(bot_config, "llm_model", "gemini-2.5-flash"),
                     thinking_enabled=thinking_enabled)

    # --- End-call tool ---
    # Task ref is set after PipelineTask creation (handler needs it to queue EndFrame)
    _task_ref: list[PipelineTask | None] = [None]

    # GPT-OSS-20B (reasoning model) has severe tool-calling instability:
    # it calls end_call on the first turn, gets blocked, then spirals into
    # 30+ second reasoning loops producing no text. Skip tools entirely for
    # reasoning models; rely on max_call_duration for call ending.
    llm_model = getattr(bot_config, "llm_model", "")
    _groq_no_tools = llm_provider == "groq" and "gpt-oss" in llm_model

    async def handle_end_call(params):
        reason = params.arguments.get("reason", "conversation_ended")
        logger.info("end_call_triggered", call_sid=call_context.call_sid, reason=reason,
                     provider=llm_provider)
        # Store LLM's reason on CallGuard so it's available in post-call metadata
        call_guard.llm_end_reason = reason
        await params.result_callback("Call ending now. Do not say anything else.")
        if _task_ref[0]:
            await _task_ref[0].queue_frame(EndFrame())

    # --- During-call workflow tools ---
    workflow_tool_schema, workflow_handler = _build_workflow_tools(bot_config, call_context)

    # --- Callback tool ---
    callback_tool_schema, callback_handler = _build_callback_tool(bot_config, call_context)

    # --- Bot switch tool ---
    switch_tool_schema, switch_handler = _build_switch_bot_tool(bot_config, call_context)

    if not _groq_no_tools:
        llm.register_function("end_call", handle_end_call)
        if workflow_handler:
            llm.register_function("trigger_crm_workflow", workflow_handler)
        if callback_handler:
            llm.register_function("schedule_callback", callback_handler)
        if switch_handler:
            llm.register_function("switch_bot", switch_handler)
    else:
        logger.info("tools_disabled_for_model", model=llm_model, provider=llm_provider)

    # --- TTS ---
    tts_provider = getattr(bot_config, "tts_provider", "sarvam")
    logger.info("tts_provider_debug", tts_provider=tts_provider, voice=call_context.tts_voice,
                bot_has_attr=hasattr(bot_config, "tts_provider"),
                bot_raw=getattr(bot_config, "tts_provider", "MISSING"))

    if tts_provider == "sarvam":
        from pipecat.services.sarvam.tts import SarvamTTSService

        # NOTE: TOKEN mode deadlocks with Sarvam's pause_frame_processing=True.
        # Each token triggers run_tts() which pauses the processor, but single
        # tokens are below min_buffer_size so Sarvam never returns audio →
        # processor stays paused → no more tokens flow → deadlock.
        # SENTENCE mode (default) sends full sentences which always exceed
        # min_buffer_size, avoiding the deadlock.
        tts_lang = "en-IN" if stt_language in ("unknown", "multi") else stt_language
        tts = SarvamTTSService(
            api_key=settings.SARVAM_API_KEY,
            model="bulbul:v3",
            voice_id=call_context.tts_voice,
            sample_rate=16000,
            text_aggregator=PhraseTextAggregator(
                min_phrase_chars=30,
                subsequent_phrase_chars=50,
                adaptive=settings.ADAPTIVE_PHRASE_CHARS,
            ),
            params=SarvamTTSService.InputParams(
                language=tts_lang,
                min_buffer_size=30,
                max_chunk_length=100,
                temperature=0.7,
            ),
        )
        logger.info("tts_sarvam_init", voice=call_context.tts_voice, model="bulbul:v3")

    elif tts_provider == "gemini":
        from pipecat.services.google.tts import GeminiTTSService
        from pipecat.transcriptions.language import Language

        voice_id = _CHIRP_TO_GEMINI_VOICE.get(
            call_context.tts_voice, call_context.tts_voice
        )

        GeminiTTS = _get_gemini_tts_class()

        # Resolve language enum from BCP-47 code
        lang_enum_name = _LANG_CODE_TO_ENUM.get(stt_language, "EN_IN")
        tts_language = getattr(Language, lang_enum_name, Language.EN_IN)

        tts = GeminiTTS(
            model="gemini-2.5-flash-tts",
            voice_id=voice_id,
            sample_rate=24000,
            text_aggregator=PhraseTextAggregator(
                min_phrase_chars=10,
                subsequent_phrase_chars=25,
                adaptive=settings.ADAPTIVE_PHRASE_CHARS,
            ),
            params=GeminiTTSService.InputParams(
                language=tts_language,
            ),
        )
    elif tts_provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        tts = ElevenLabsTTSService(
            api_key=settings.ELEVENLABS_API_KEY,
            voice_id=call_context.tts_voice,
            model="eleven_flash_v2_5",
            sample_rate=16000,
            text_aggregator=PhraseTextAggregator(
                min_phrase_chars=35,
                subsequent_phrase_chars=50,
                adaptive=settings.ADAPTIVE_PHRASE_CHARS,
            ),
            params=ElevenLabsTTSService.InputParams(
                stability=0.5,
                similarity_boost=0.75,
                use_speaker_boost=False,
                style=0.0,
            ),
        )
        logger.info("tts_elevenlabs_init", voice=call_context.tts_voice, model="eleven_flash_v2_5")
    else:
        from app.services.google_cloud_tts import GoogleCloudGRPCTTSService

        tts = GoogleCloudGRPCTTSService(
            voice_name=call_context.tts_voice,
            language_code="en-IN" if stt_language in ("unknown", "multi") else stt_language,
            sample_rate=16000,
            audio_encoding="PCM",
        )

    # --- Context ---
    system_prompt = call_context.filled_prompt.strip()
    if _CONVERSATION_RULES.strip():
        system_prompt = f"{system_prompt}\n\n{_CONVERSATION_RULES.strip()}"
    # Seed greeting into context so the LLM knows it was already spoken and
    # doesn't generate a second greeting on its first turn.
    # When greeting_text is provided AND greeting was sent directly (bypassing
    # pipeline TTS), we pre-seed it here. When TTSSpeakFrame is used instead,
    # context_aggregator.assistant() captures the TTS output automatically.
    messages = [{"role": "system", "content": system_prompt}]
    if greeting_text:
        messages.append({"role": "assistant", "content": greeting_text})
    context = OpenAILLMContext(messages=messages)

    # Set tools as provider-agnostic ToolsSchema — adapters auto-convert per LLM provider
    if not _groq_no_tools:
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        standard_tools = [_build_end_call_tool()]
        if workflow_tool_schema:
            standard_tools.append(workflow_tool_schema)
        if callback_tool_schema:
            standard_tools.append(callback_tool_schema)
        if switch_tool_schema:
            standard_tools.append(switch_tool_schema)
        context.set_tools(ToolsSchema(standard_tools=standard_tools))

    # --- Context aggregator ---
    context_aggregator = llm.create_context_aggregator(context)

    # NOTE: No push_aggregation patch. Previous attempts to add a "Sorry,
    # I didn't catch that" fallback all failed because push_aggregation is
    # called every 0.5s on echo/noise (not just on real turn boundaries),
    # and _seen_interim_results persists across turns. With language="multi"
    # on Deepgram, Hindi/Hinglish is now transcribed properly. If STT still
    # misses something, the idle handler (below) will re-engage after timeout.

    # --- Silence watchdog ---
    # Replaces deprecated UserIdleProcessor which fails to fire with Sarvam STT.
    # Uses polling-based timer: 1st timeout → "Hello?", 2nd → goodbye + hangup.
    silence_timeout = max(float(call_context.silence_timeout_secs), 12.0)
    silence_watchdog = SilenceWatchdog(
        timeout=silence_timeout,
        call_sid=call_context.call_sid,
    )

    # --- Call guard (voicemail / hold / DND detection + custom red flags) ---
    goal_cfg = getattr(bot_config, "goal_config", None)
    if isinstance(goal_cfg, str):
        import json
        goal_cfg = json.loads(goal_cfg)
    call_guard = CallGuard(call_sid=call_context.call_sid, goal_config=goal_cfg)

    # --- Latency trackers ---
    tracker_post_stt = LatencyTracker(position="post_stt", call_sid=call_context.call_sid)
    tracker_post_tts = LatencyTracker(position="post_tts", call_sid=call_context.call_sid)

    # --- Pipeline ---
    # TTSTailTrim only needed for Sarvam (drops pathological silent tails)
    tts_processors = [tts]
    if tts_provider == "sarvam":
        tts_processors.append(TTSTailTrim(call_sid=call_context.call_sid))

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            call_guard,
            tracker_post_stt,
            silence_watchdog,
            context_aggregator.user(),
            llm,
            *tts_processors,
            tracker_post_tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            interruption_strategies=[MinWordsInterruptionStrategy(min_words=2)],
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # Set task ref so end_call handler and silence watchdog can queue EndFrame
    _task_ref[0] = task
    silence_watchdog.set_task(task)

    return task, transport, context, call_guard
