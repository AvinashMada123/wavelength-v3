"""
Build a per-call Pipecat pipeline from bot config and call context.

Returns (PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext).
"""

from __future__ import annotations

import time

import pipecat.transports.base_output as _base_output
import structlog
from deepgram import LiveOptions

# Increase from 0.35s default to survive inter-sentence TTS gaps (worst TTFB: 1.943s).
# Safe: no pipeline component depends on BotStoppedSpeakingFrame timing for turn-taking.
_base_output.BOT_VAD_STOP_SECS = 3.0

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.interruptions.min_words_interruption_strategy import MinWordsInterruptionStrategy
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.user_idle_processor import UserIdleProcessor
from app.serializers.plivo_pcm import PlivoPCMFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.llm import GoogleLLMService
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
from app.pipeline.idle_handler import IdleEscalationHandler

_timing_logger = structlog.get_logger("pipeline.timing")

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


class LatencyTracker(FrameProcessor):
    """Pass-through processor that logs timestamps for specific frame types.

    Inserted at key pipeline positions to measure per-stage latency.
    Passes ALL frames through unconditionally.
    """

    # Import frame types lazily to avoid circular imports at module level.
    _frame_types: dict | None = None

    @classmethod
    def _load_frame_types(cls):
        if cls._frame_types is not None:
            return
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame,
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

    def __init__(self, position: str, call_sid: str, **kwargs):
        super().__init__(name=f"LatencyTracker-{position}", **kwargs)
        self._position = position
        self._call_sid = call_sid
        self._turn_id = 0
        self._seen_this_turn: set[str] = set()
        self._load_frame_types()

    async def process_frame(self, frame, direction: FrameDirection):
        from pipecat.frames.frames import StartFrame, UserStoppedSpeakingFrame

        # Must handle StartFrame to initialize, then push it downstream.
        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        # Reset tracking on new turn.
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._turn_id += 1
            self._seen_this_turn = set()

        # Log first occurrence of each tracked frame type per turn.
        for label, frame_type in self._frame_types.items():
            if isinstance(frame, frame_type) and label not in self._seen_this_turn:
                self._seen_this_turn.add(label)
                _timing_logger.info(
                    "latency_event",
                    position=self._position,
                    stage=label,
                    turn=self._turn_id,
                    call_sid=self._call_sid,
                    ts=time.monotonic(),
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


async def build_pipeline(
    bot_config: BotConfig,
    call_context: CallContext,
    websocket: WebSocket,
) -> tuple[PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext, PlivoPCMFrameSerializer]:
    """
    Construct an isolated Pipecat pipeline for a single call.

    Args:
        bot_config: Loaded from DB — contains voice, timeouts, credentials.
        call_context: Per-call data — filled prompt, contact info, call_sid.
        websocket: The accepted FastAPI WebSocket connection from Plivo.

    Returns:
        (task, transport, context, serializer) — context for messages, serializer for recordings.
    """

    # --- Serializer (extracted for post-call recording access) ---
    serializer = PlivoPCMFrameSerializer(
        stream_id=call_context.call_sid,
        record=True,
    )

    # --- Transport ---
    # VAD and turn analyzer go on transport params in pipecat 0.0.104.
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=16000,
            audio_out_10ms_chunks=2,
            add_wav_header=False,
            serializer=serializer,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(stop_secs=0.5),
            ),
        ),
    )

    # --- STT ---
    stt_language = getattr(call_context, "language", "en-IN") or "en-IN"
    stt = DeepgramSTTService(
        api_key=settings.DEEPGRAM_API_KEY,
        live_options=LiveOptions(
            model="nova-2-general",
            language=stt_language,
            interim_results=True,
            utterance_end_ms="1000",
            punctuate=True,
            smart_format=True,
        ),
    )

    # --- LLM ---
    llm = GoogleLLMService(
        api_key=settings.GOOGLE_AI_API_KEY,
        model="gemini-2.5-flash-lite",
        params=GoogleLLMService.InputParams(
            temperature=0.7,
            max_tokens=256,
        ),
    )

    # --- TTS ---
    if settings.TTS_PROVIDER == "gemini":
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
            params=GeminiTTSService.InputParams(
                language=tts_language,
            ),
        )
    else:
        from app.services.google_cloud_tts import GoogleCloudGRPCTTSService

        tts = GoogleCloudGRPCTTSService(
            voice_name=call_context.tts_voice,
            language_code=stt_language,
            sample_rate=16000,
            audio_encoding="PCM",
        )

    # --- Context ---
    context = OpenAILLMContext(
        messages=[{"role": "system", "content": call_context.filled_prompt}]
    )

    # --- Context aggregator ---
    context_aggregator = llm.create_context_aggregator(context)

    # --- Idle handler ---
    idle_handler = IdleEscalationHandler(
        silence_timeout=call_context.silence_timeout_secs,
    )

    async def on_idle(processor, retry_count):
        """Called by UserIdleProcessor when user is idle. Returns True to keep monitoring."""
        return await idle_handler.on_idle(processor, retry_count)

    user_idle = UserIdleProcessor(
        callback=on_idle,
        timeout=float(call_context.silence_timeout_secs),
    )

    # --- Latency trackers ---
    tracker_post_stt = LatencyTracker(position="post_stt", call_sid=call_context.call_sid)
    tracker_post_tts = LatencyTracker(position="post_tts", call_sid=call_context.call_sid)

    # --- Pipeline ---
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            tracker_post_stt,
            user_idle,
            context_aggregator.user(),
            llm,
            tts,
            tracker_post_tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            interruption_strategies=[MinWordsInterruptionStrategy(min_words=1)],
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    return task, transport, context, serializer
