"""
Build a per-call Pipecat pipeline from bot config and call context.

Returns (PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext).
"""

from __future__ import annotations

import collections
import time

import pipecat.transports.base_output as _base_output
import structlog
from deepgram import LiveOptions

# Increase from 0.35s default to survive inter-sentence TTS gaps.
# 1.5s is safe for Sarvam TTS (0.2s TTFB) while reducing post-speech dead zone.
_base_output.BOT_VAD_STOP_SECS = 1.5

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.interruptions.min_words_interruption_strategy import MinWordsInterruptionStrategy
from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.user_idle_processor import UserIdleProcessor
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
from app.pipeline.idle_handler import IdleEscalationHandler

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

# Universal phone call quality rules appended to every system prompt.
_CONVERSATION_RULES = """

PHONE CALL RULES (always follow):
- HARD LIMIT: Maximum 2 sentences per turn, then STOP and let the customer speak.
- Default turns: under 25 words. Detailed answers: under 40 words.
- After asking ANY question, your turn is OVER. Do NOT continue talking. Do NOT answer your own question.
- NEVER repeat a question you already asked, even rephrased.
- Use a DIFFERENT acknowledgment each turn. Never start two consecutive turns the same way.
  Rotate from: "Right" / "Hmm okay" / "I see" / "Interesting" / "Got it" / "Fair enough" / "Okay so"
- BANNED phrases: "umm", "great question", "Absolutely", "That is absolutely correct", "I appreciate your time"
- Audio issues: say "Sorry, I didn't catch that. Could you repeat?"
- "Not interested" is not always goodbye — explore what's holding them back before ending.
- If you already said goodbye and the customer responds with bye, do NOT say goodbye again.
- If you said goodbye but the customer says "wait" or keeps talking, you MUST respond.
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


class STTAudioGate(FrameProcessor):
    """Mute echo audio during the initial greeting only.

    Plivo echoes bot audio back through the WebSocket. During the greeting,
    this echo can confuse Deepgram (especially multi-language mode). This
    gate sends silence to STT for the first `gate_secs` seconds after the
    pipeline starts, then permanently opens.

    Only the greeting is gated — subsequent bot speech is NOT muted, because
    BotStoppedSpeakingFrame fires BOT_VAD_STOP_SECS (1.5s) late, which
    would eat the start of user responses (short utterances like "Yeah"
    are lost entirely).
    """

    def __init__(self, gate_secs: float = 5.0, call_sid: str = "", **kwargs):
        super().__init__(name="STTAudioGate", **kwargs)
        self._call_sid = call_sid
        self._gate_secs = gate_secs
        self._start_time: float | None = None

    async def process_frame(self, frame, direction: FrameDirection):
        import time

        from pipecat.frames.frames import InputAudioRawFrame, StartFrame

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            self._start_time = time.monotonic()
            await self.push_frame(frame, direction)
            return

        # Only mute during the greeting window
        if (
            isinstance(frame, InputAudioRawFrame)
            and self._start_time is not None
            and (time.monotonic() - self._start_time) < self._gate_secs
        ):
            silent = InputAudioRawFrame(
                audio=b"\x00" * len(frame.audio),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
            await self.push_frame(silent, direction)
            return

        await self.push_frame(frame, direction)


class TTSJitterBuffer(FrameProcessor):
    """Continuous reservoir buffer absorbing Sarvam TTS WebSocket jitter.

    Sarvam TTS delivers audio chunks with 200-950ms timing jitter. The
    transport sends at 2x real-time, so its queue drains fast and every
    delivery gap = dead silence on the phone.

    Two-phase approach:
      1. Initial fill: Accumulates `initial_buffer_ms` before releasing
         any audio. Only for the first sentence of each bot response.
      2. Streaming: Releases audio while maintaining `min_reserve_ms` in
         the reservoir. Continuation sentences skip the initial fill —
         the min_reserve provides natural buffering at sentence boundaries.

    At 2x transport send speed, min_reserve_ms of 400 gives ~200ms of
    real-time jitter absorption throughout each utterance.
    """

    def __init__(
        self,
        initial_buffer_ms: int = 800,
        min_reserve_ms: int = 400,
        call_sid: str = "",
        **kwargs,
    ):
        super().__init__(name="TTSJitterBuffer", **kwargs)
        self._call_sid = call_sid
        # Bytes = ms * 16000 samples/sec * 2 bytes/sample / 1000
        self._initial_target_bytes = int(16000 * initial_buffer_ms / 1000 * 2)
        self._min_reserve_bytes = int(16000 * min_reserve_ms / 1000 * 2)
        self._reservoir: collections.deque = collections.deque()
        self._reservoir_bytes = 0
        self._phase = "idle"  # idle | filling | streaming
        self._last_stopped_time: float = 0

    async def process_frame(self, frame, direction: FrameDirection):
        import time

        from pipecat.frames.frames import (
            StartFrame,
            TTSAudioRawFrame,
            TTSStartedFrame,
            TTSStoppedFrame,
        )

        if isinstance(frame, StartFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSStartedFrame):
            now = time.monotonic()
            # Continuation sentence (< 2s gap) skips initial fill
            if self._last_stopped_time and (now - self._last_stopped_time) < 2.0:
                self._phase = "streaming"
            else:
                self._phase = "filling"
            self._reservoir.clear()
            self._reservoir_bytes = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSAudioRawFrame) and self._phase in (
            "filling",
            "streaming",
        ):
            self._reservoir.append((frame, direction))
            self._reservoir_bytes += len(frame.audio)

            if self._phase == "filling":
                if self._reservoir_bytes >= self._initial_target_bytes:
                    self._phase = "streaming"
                    await self._release_above_reserve()
            else:
                await self._release_above_reserve()
            return

        if isinstance(frame, TTSStoppedFrame):
            await self._flush_all()
            self._phase = "idle"
            self._last_stopped_time = time.monotonic()
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def _release_above_reserve(self):
        """Release frames while keeping min_reserve_bytes in the reservoir."""
        while self._reservoir and self._reservoir_bytes > self._min_reserve_bytes:
            frame, direction = self._reservoir.popleft()
            self._reservoir_bytes -= len(frame.audio)
            await self.push_frame(frame, direction)

    async def _flush_all(self):
        """Release all remaining frames."""
        for frame, direction in self._reservoir:
            await self.push_frame(frame, direction)
        self._reservoir.clear()
        self._reservoir_bytes = 0


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


def _build_workflow_tools(bot_config: BotConfig, call_context: CallContext):
    """Build LLM tool definitions and handler for during-call CRM workflows."""
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

    from google.genai import types

    tools = [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="trigger_crm_workflow",
                    description=(
                        "Trigger a CRM workflow to tag the contact. "
                        "Use this when the conversation matches a workflow's trigger condition.\n\n"
                        f"Available workflows:\n{wf_descriptions}"
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "workflow_id": types.Schema(
                                type="STRING",
                                description="The ID of the workflow to trigger",
                                enum=[wf["id"] for wf in during_call],
                            )
                        },
                        required=["workflow_id"],
                    ),
                )
            ]
        )
    ]

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

    return tools, handle_trigger_workflow


def _build_end_call_tool():
    """Build the end_call LLM tool definition in Google-native format."""
    from google.genai import types

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
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
                    "- The customer only said 'yeah', 'yes', 'okay', 'thank you', or 'hmm' after your goodbye — "
                    "these are acknowledgments, NOT goodbyes. Wait for them to finish or say an actual goodbye word.\n"
                    "- The customer is still mid-sentence, stuttering, or starting a new question.\n"
                    "- The customer is hesitant but has NOT explicitly said goodbye or rejected.\n"
                    "- You are unsure whether the customer wants to end — keep the conversation going instead."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "reason": types.Schema(
                            type="STRING",
                            description="Brief reason for ending the call (e.g., 'mutual_goodbye', 'not_interested', 'wrong_number')",
                        )
                    },
                    required=["reason"],
                ),
            )
        ]
    )


async def build_pipeline(
    bot_config: BotConfig,
    call_context: CallContext,
    websocket: WebSocket,
    provider: str = "plivo",
    stream_sid: str = "",
) -> tuple[PipelineTask, FastAPIWebsocketTransport, OpenAILLMContext, CallGuard]:
    """
    Construct an isolated Pipecat pipeline for a single call.

    Args:
        bot_config: Loaded from DB — contains voice, timeouts, credentials.
        call_context: Per-call data — filled prompt, contact info, call_sid.
        websocket: The accepted FastAPI WebSocket connection from Plivo/Twilio.
        provider: "plivo" or "twilio" — determines serializer and audio format.

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
    # Use multi-language detection for Indian languages — users frequently
    # code-switch between Hindi/Hinglish/English and en-IN misses Hindi entirely,
    # causing bot to go silent (no transcript → no LLM response).
    _MULTILANG_PREFIXES = ("en-IN", "hi", "mr", "ta", "te", "bn", "gu", "kn", "ml")
    deepgram_language = "multi" if stt_language.startswith(_MULTILANG_PREFIXES) else stt_language
    stt = DeepgramSTTService(
        api_key=settings.DEEPGRAM_API_KEY,
        live_options=LiveOptions(
            model="nova-2-general",
            language=deepgram_language,
            interim_results=True,
            utterance_end_ms="1000",
            punctuate=True,
            smart_format=True,
        ),
    )

    # --- LLM (Vertex AI) ---
    llm = GoogleVertexLLMService(
        credentials_path=settings.GOOGLE_APPLICATION_CREDENTIALS,
        project_id=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.VERTEX_AI_LOCATION,
        model="gemini-2.5-flash",
        params=GoogleLLMService.InputParams(
            temperature=0.7,
            max_tokens=256,
        ),
    )

    # --- End-call tool ---
    # Task ref is set after PipelineTask creation (handler needs it to queue EndFrame)
    _task_ref: list[PipelineTask | None] = [None]

    async def handle_end_call(params):
        reason = params.arguments.get("reason", "conversation_ended")
        logger.info("end_call_triggered", call_sid=call_context.call_sid, reason=reason)
        await params.result_callback("Call ending now. Do not say anything else.")
        if _task_ref[0]:
            await _task_ref[0].queue_frame(EndFrame())

    llm.register_function("end_call", handle_end_call)

    # --- During-call workflow tools ---
    workflow_tools, workflow_handler = _build_workflow_tools(bot_config, call_context)
    if workflow_handler:
        llm.register_function("trigger_crm_workflow", workflow_handler)

    # --- TTS ---
    tts_provider = getattr(bot_config, "tts_provider", "gemini")
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
        tts = SarvamTTSService(
            api_key=settings.SARVAM_API_KEY,
            model="bulbul:v3",
            voice_id=call_context.tts_voice,
            sample_rate=16000,
            params=SarvamTTSService.InputParams(
                language=stt_language,
                min_buffer_size=30,
                max_chunk_length=100,
                temperature=0.4,
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
    system_prompt = call_context.filled_prompt + _CONVERSATION_RULES
    # NOTE: Greeting is NOT seeded here — TTSSpeakFrame goes through TTS →
    # context_aggregator.assistant() which adds it automatically. Adding it
    # here too causes a duplicate greeting in LLM context (wastes tokens).
    context = OpenAILLMContext(
        messages=[
            {"role": "system", "content": system_prompt},
        ],
    )

    # Set tools in Google-native format (context.tools property has no setter, use set_tools)
    all_tools = [_build_end_call_tool()]
    if workflow_tools:
        all_tools.extend(workflow_tools)
    context.set_tools(all_tools)

    # --- Context aggregator ---
    context_aggregator = llm.create_context_aggregator(context)

    # NOTE: No push_aggregation patch. Previous attempts to add a "Sorry,
    # I didn't catch that" fallback all failed because push_aggregation is
    # called every 0.5s on echo/noise (not just on real turn boundaries),
    # and _seen_interim_results persists across turns. With language="multi"
    # on Deepgram, Hindi/Hinglish is now transcribed properly. If STT still
    # misses something, the idle handler (below) will re-engage after timeout.

    # --- Idle handler ---
    idle_handler = IdleEscalationHandler(
        silence_timeout=call_context.silence_timeout_secs,
    )

    async def on_idle(processor, retry_count):
        """Called by UserIdleProcessor when user is idle. Returns True to keep monitoring."""
        return await idle_handler.on_idle(processor, retry_count)

    # Minimum 12s: idle timer counts from last USER speech, not from when bot
    # finishes speaking. Short timeouts fire while TTS is still playing.
    idle_timeout = max(float(call_context.silence_timeout_secs), 12.0)
    user_idle = UserIdleProcessor(
        callback=on_idle,
        timeout=idle_timeout,
    )

    # --- Call guard (voicemail / hold / DND detection + custom red flags) ---
    goal_cfg = getattr(bot_config, "goal_config", None)
    if isinstance(goal_cfg, str):
        import json
        goal_cfg = json.loads(goal_cfg)
    call_guard = CallGuard(call_sid=call_context.call_sid, goal_config=goal_cfg)

    # --- Greeting guard (suppress phantom VAD during initial greeting) ---
    greeting_guard = GreetingGuard(
        guard_duration=5.0,
        call_sid=call_context.call_sid,
    )

    # --- STT audio gate (mute echo during greeting only) ---
    stt_gate = STTAudioGate(
        gate_secs=5.0,
        call_sid=call_context.call_sid,
    )

    # --- TTS jitter buffer (absorb Sarvam WebSocket streaming gaps) ---
    jitter_buffer = TTSJitterBuffer(
        initial_buffer_ms=800,
        min_reserve_ms=400,
        call_sid=call_context.call_sid,
    ) if tts_provider == "sarvam" else None

    # --- Latency trackers ---
    tracker_post_stt = LatencyTracker(position="post_stt", call_sid=call_context.call_sid)
    tracker_post_tts = LatencyTracker(position="post_tts", call_sid=call_context.call_sid)

    # --- Pipeline ---
    # Build processor list — jitter buffer is only added for Sarvam TTS
    post_tts_processors = [tracker_post_tts]
    if jitter_buffer:
        post_tts_processors.append(jitter_buffer)

    pipeline = Pipeline(
        [
            transport.input(),
            stt_gate,
            stt,
            call_guard,
            tracker_post_stt,
            user_idle,
            greeting_guard,
            context_aggregator.user(),
            llm,
            tts,
            *post_tts_processors,
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

    # Set task ref so end_call handler can queue EndFrame
    _task_ref[0] = task

    return task, transport, context, call_guard
