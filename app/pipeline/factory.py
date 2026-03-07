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
from pipecat.frames.frames import EndFrame
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

from app.config import gemini_key_pool, settings
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
            await params.result_callback("Could not find contact in CRM")
            return

        from app.ghl.client import GHLClient

        ghl = GHLClient(api_key=api_key)
        try:
            tag = wf["tag"]
            ok = await ghl.tag_contact(contact_id, tag)
            logger.info(
                "during_call_workflow_triggered",
                call_sid=call_context.call_sid,
                workflow=wf.get("name"),
                tag=tag,
                success=ok,
            )
            await params.result_callback(
                f"Done — tagged contact with '{tag}'" if ok else f"Failed to tag with '{tag}'"
            )
        finally:
            await ghl.close()

    return tools, handle_trigger_workflow


def _build_end_call_tool():
    """Build the end_call LLM tool definition in Google-native format."""
    from google.genai import types

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="end_call",
                description=(
                    "End the phone call. Call this IMMEDIATELY when:\n"
                    "1) Both you AND the customer have said goodbye/bye/take care — call end_call with NO additional text.\n"
                    "2) The customer says 'not interested', 'don't call me', 'wrong number', or any clear rejection "
                    "after you've attempted to address their concern.\n"
                    "3) The customer explicitly asks to hang up or end the call.\n\n"
                    "IMPORTANT: If you already said goodbye and the customer responds with "
                    "'bye'/'okay bye'/'thanks bye', call end_call IMMEDIATELY without saying anything else. "
                    "Do NOT say goodbye twice."
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
            stream_sid="",  # Updated by Twilio's 'start' event
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

    # --- LLM (key from round-robin pool) ---
    call_api_key = gemini_key_pool.get_key()
    llm = GoogleLLMService(
        api_key=call_api_key,
        model="gemini-2.5-flash-lite",
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

    if tts_provider == "sarvam":
        from pipecat.services.sarvam.tts import SarvamTTSService

        tts = SarvamTTSService(
            api_key=settings.SARVAM_API_KEY,
            model="bulbul:v3",
            voice_id=call_context.tts_voice,
            sample_rate=16000,
            params=SarvamTTSService.InputParams(
                language=stt_language,
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
    # NOTE: Tools removed — OpenAILLMContext converts Google-native Tool objects
    # to OpenAI format, which Google's SDK then rejects. Call ends via hangup,
    # idle timeout, or max duration instead.
    system_prompt = call_context.filled_prompt + _CONVERSATION_RULES
    context = OpenAILLMContext(
        messages=[{"role": "system", "content": system_prompt}],
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

    # --- Call guard (voicemail / hold / DND detection) ---
    call_guard = CallGuard(call_sid=call_context.call_sid)

    # --- Latency trackers ---
    tracker_post_stt = LatencyTracker(position="post_stt", call_sid=call_context.call_sid)
    tracker_post_tts = LatencyTracker(position="post_tts", call_sid=call_context.call_sid)

    # --- Pipeline ---
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            call_guard,
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

    # Set task ref so end_call handler can queue EndFrame
    _task_ref[0] = task

    return task, transport, context, call_guard
