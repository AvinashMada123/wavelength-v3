"""
Pipeline runner and post-call summary generation.

run_pipeline() starts and manages the Pipecat pipeline for a single call.
generate_call_summary() makes a non-streaming Gemini call to summarize the conversation
and classify the lead's interest level.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time

import aiohttp
import structlog
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.pipeline.runner import PipelineRunner
from starlette.websockets import WebSocket

from app.config import gemini_key_pool, settings
from app.models.bot_config import BotConfig
from app.models.schemas import CallContext
from app.pipeline.factory import build_pipeline
from app.serializers.plivo_pcm import PLIVO_SAMPLE_RATE, ComfortNoiseInjector

logger = structlog.get_logger(__name__)

_DEFAULT_GREETING = "Hi {contact_name}, this is {agent_name} calling from {company_name}. How are you doing today?"


def _resolve_greeting_text(ctx: CallContext, bot_config: BotConfig) -> str:
    """Resolve the greeting template into final text.

    Uses callback_greeting_template for returning callers (when call memory is present).
    """
    # Check if this is a returning caller by looking for memory in the prompt
    is_returning = "PREVIOUS CALL HISTORY WITH THIS CONTACT" in (ctx.filled_prompt or "")
    callback_greeting = getattr(bot_config, "callback_greeting_template", None)

    if is_returning and callback_greeting:
        greeting_template = callback_greeting
    else:
        greeting_template = getattr(bot_config, "greeting_template", None) or _DEFAULT_GREETING
    _greeting_vars = {
        "name": ctx.contact_name or "there",
        "contact_name": ctx.contact_name or "there",
        "customer_name": ctx.contact_name or "there",
        "agent_name": bot_config.agent_name,
        "company_name": bot_config.company_name,
        "event_name": getattr(bot_config, "event_name", None) or "",
        "event_date": getattr(bot_config, "event_date", None) or "",
        "event_time": getattr(bot_config, "event_time", None) or "",
        "location": getattr(bot_config, "location", None) or "",
    }

    class _WarnMissing(dict):
        def __missing__(self, key):
            logger.warning("greeting_template_missing_var", var=key, call_sid=ctx.call_sid)
            return ""

    text = greeting_template.format_map(_WarnMissing(_greeting_vars))
    if not text.strip():
        text = _DEFAULT_GREETING.format_map(_greeting_vars)
    return text


async def _synthesize_greeting(
    greeting_text: str,
    bot_config: BotConfig,
    call_context: CallContext,
) -> bytes | None:
    """Synthesize greeting audio using a standalone TTS instance.

    Returns raw PCM bytes at 16kHz, or None on failure.
    """
    tts_provider = getattr(bot_config, "tts_provider", "sarvam")
    stt_language = getattr(call_context, "language", "en-IN") or "en-IN"

    try:
        if tts_provider == "gemini":
            from app.pipeline.factory import _get_gemini_tts_class, _CHIRP_TO_GEMINI_VOICE, _LANG_CODE_TO_ENUM
            from pipecat.services.google.tts import GeminiTTSService
            from pipecat.transcriptions.language import Language

            voice_id = _CHIRP_TO_GEMINI_VOICE.get(call_context.tts_voice, call_context.tts_voice)
            lang_enum_name = _LANG_CODE_TO_ENUM.get(stt_language, "EN_IN")
            tts_language = getattr(Language, lang_enum_name, Language.EN_IN)

            GeminiTTS = _get_gemini_tts_class()
            tts = GeminiTTS(
                model="gemini-2.5-flash-tts",
                voice_id=voice_id,
                params=GeminiTTSService.InputParams(language=tts_language),
            )
        elif tts_provider == "sarvam":
            from pipecat.services.sarvam.tts import SarvamTTSService

            tts_lang = "en-IN" if stt_language in ("unknown", "multi") else stt_language
            tts = SarvamTTSService(
                api_key=settings.SARVAM_API_KEY,
                model="bulbul:v3",
                voice_id=call_context.tts_voice,
                sample_rate=16000,
                params=SarvamTTSService.InputParams(
                    language=tts_lang,
                    min_buffer_size=30,
                    max_chunk_length=100,
                    temperature=0.4,
                    pace=1.1,
                ),
            )
        elif tts_provider == "elevenlabs":
            from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

            tts = ElevenLabsHttpTTSService(
                api_key=settings.ELEVENLABS_API_KEY,
                voice_id=call_context.tts_voice,
                model="eleven_flash_v2_5",
                sample_rate=16000,
                aiohttp_session=aiohttp.ClientSession(),
                params=ElevenLabsHttpTTSService.InputParams(
                    stability=0.5,
                    similarity_boost=0.75,
                    use_speaker_boost=False,
                    style=0.0,
                ),
            )
        else:
            # Google Cloud TTS — not easily usable standalone, fall back
            return None

        # Collect all audio frames from the async generator
        audio_chunks: list[bytes] = []
        start = time.monotonic()
        async for frame in tts.run_tts(greeting_text, context_id=call_context.call_sid):
            if hasattr(frame, "audio") and frame.audio:
                audio_chunks.append(frame.audio)

        synth_ms = round((time.monotonic() - start) * 1000)
        if not audio_chunks:
            logger.warning("greeting_synth_empty", call_sid=call_context.call_sid)
            return None

        pcm_bytes = b"".join(audio_chunks)
        logger.info(
            "greeting_synth_ok",
            call_sid=call_context.call_sid,
            synth_ms=synth_ms,
            bytes=len(pcm_bytes),
            duration_ms=round(len(pcm_bytes) / (PLIVO_SAMPLE_RATE * 2) * 1000),
        )
        return pcm_bytes

    except Exception as e:
        logger.error("greeting_synth_failed", call_sid=call_context.call_sid, error=str(e))
        return None


def _mix_ambient_into_greeting(pcm_bytes: bytes, preset_name: str, volume: float) -> bytes:
    """Mix ambient noise into greeting PCM bytes. Returns original on error."""
    try:
        import numpy as np

        from app.audio.ambient import get_preset

        buf = get_preset(preset_name)
        if buf is None or len(pcm_bytes) < 2:
            return pcm_bytes

        volume = min(max(volume, 0.0), 0.3)
        speech = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        n_samples = len(speech)

        # Tile noise buffer to match greeting length
        repeats = (n_samples // len(buf)) + 1
        noise = np.tile(buf.astype(np.float32), repeats)[:n_samples]

        mixed = speech + noise * volume
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        logger.exception("ambient_greeting_mix_failed")
        return pcm_bytes


async def _send_greeting_to_plivo(
    websocket: WebSocket,
    pcm_bytes: bytes,
    call_sid: str,
    chunk_size: int = 640,
) -> bool:
    """Send pre-synthesized greeting audio directly to Plivo via playAudio frames.

    Returns True if all frames were sent successfully.
    """
    try:
        n_chunks = 0
        for offset in range(0, len(pcm_bytes), chunk_size):
            chunk = pcm_bytes[offset: offset + chunk_size]
            payload = base64.b64encode(chunk).decode("utf-8")
            msg = json.dumps({
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-l16",
                    "sampleRate": PLIVO_SAMPLE_RATE,
                    "payload": payload,
                },
            })
            await websocket.send_text(msg)
            n_chunks += 1

        # Send checkpoint to confirm greeting delivery
        await websocket.send_text(json.dumps({
            "event": "checkpoint",
            "name": "greeting_complete",
        }))

        logger.info(
            "greeting_direct_play_sent",
            call_sid=call_sid,
            chunks=n_chunks,
            bytes=len(pcm_bytes),
        )
        return True
    except Exception as e:
        logger.error("greeting_direct_play_failed", call_sid=call_sid, error=str(e))
        return False


async def run_pipeline(
    websocket: WebSocket,
    ctx: CallContext,
    bot_config: BotConfig,
    provider: str = "plivo",
    stream_sid: str = "",
    plivo_stream_id: str = "",
    greeting_audio: bytes | None = None,
) -> dict:
    """
    Build and run the Pipecat pipeline for a single call.

    Args:
        plivo_stream_id: Pre-captured Plivo stream ID from start event (Phase 3).
        greeting_audio: Pre-synthesized greeting PCM bytes (Phase 3).
            If provided, sent directly to Plivo before pipeline starts.

    Returns dict with:
      - "messages": conversation message history (list of {role, content} dicts)
    """
    # Resolve greeting text (needed for both direct play and fallback)
    greeting_text = _resolve_greeting_text(ctx, bot_config)

    # Phase 3: Send pre-synthesized greeting directly to Plivo if available
    greeting_sent_directly = False
    if settings.GREETING_DIRECT_PLAY and greeting_audio is not None:
        # Mix ambient noise into greeting so it matches pipeline TTS output
        if settings.AMBIENT_SOUND_ENABLED:
            ambient_preset = getattr(bot_config, "ambient_sound", None)
            if ambient_preset:
                ambient_vol = getattr(bot_config, "ambient_sound_volume", None) or 0.08
                greeting_audio = _mix_ambient_into_greeting(
                    greeting_audio, ambient_preset, ambient_vol
                )
        greeting_sent_directly = await _send_greeting_to_plivo(
            websocket, greeting_audio, ctx.call_sid
        )
        if greeting_sent_directly:
            # Wait briefly for playedStream confirmation (non-blocking with timeout)
            try:
                # Don't block too long — Plivo may not support checkpoint on all plans
                await asyncio.sleep(0.05)
            except Exception:
                pass

    # Prepare shared ambient cursor for mixer + injector synchronization
    ambient_preset = None
    ambient_vol = 0.08
    ambient_cursor = None
    if settings.AMBIENT_SOUND_ENABLED:
        ambient_preset = getattr(bot_config, "ambient_sound", None)
        if ambient_preset:
            ambient_vol = getattr(bot_config, "ambient_sound_volume", None) or 0.08
            from app.audio.ambient import create_loop_cursor

            ambient_cursor = create_loop_cursor()

    task, transport, context, guard = await build_pipeline(
        bot_config, ctx, websocket,
        provider=provider, stream_sid=stream_sid,
        plivo_stream_id=plivo_stream_id,
        # Only pre-seed greeting in LLM context when sent directly to Plivo
        # (bypassing pipeline TTS). When sent via TTSSpeakFrame fallback,
        # context_aggregator.assistant() captures it automatically.
        greeting_text=greeting_text if greeting_sent_directly else "",
        ambient_cursor=ambient_cursor,
    )

    max_duration = getattr(bot_config, "max_call_duration", 480) or 480
    logger.info(
        "pipeline_starting",
        call_sid=ctx.call_sid,
        voice=ctx.tts_voice,
        max_duration=max_duration,
        greeting_direct=greeting_sent_directly,
    )

    runner = PipelineRunner()

    # Phase 4b: Comfort noise / ambient noise injector (sends directly to WS)
    comfort_noise = None
    if provider == "plivo" and hasattr(transport, '_params') and hasattr(transport._params, 'serializer'):
        serializer = transport._params.serializer
        # Seed serializer timestamp after greeting so injector knows audio was playing
        if greeting_sent_directly:
            serializer._last_audio_sent_ts = time.monotonic()
        comfort_noise = ComfortNoiseInjector(
            websocket=websocket,
            serializer=serializer,
            enabled=settings.COMFORT_NOISE_ENABLED,
            ambient_preset=ambient_preset,
            ambient_volume=ambient_vol,
            loop_cursor=ambient_cursor,
        )
        comfort_noise.start()

    # Fallback: if greeting wasn't sent directly, send through pipeline
    if not greeting_sent_directly:
        async def send_initial_greeting():
            await asyncio.sleep(0.1)
            await task.queue_frame(TTSSpeakFrame(text=greeting_text))
            logger.info("initial_greeting_triggered", call_sid=ctx.call_sid, greeting=greeting_text, fallback=True)

        asyncio.create_task(send_initial_greeting())

    # Max call duration enforcement
    async def enforce_max_duration():
        try:
            await asyncio.sleep(max_duration)
            logger.info("max_call_duration_reached", call_sid=ctx.call_sid, max_duration=max_duration)
            guard.set_termination_source("max_duration")
            await task.queue_frame(EndFrame())
        except asyncio.CancelledError:
            pass

    duration_task = asyncio.create_task(enforce_max_duration())

    # Watchdog: detect WebSocket closure and stop pipeline
    async def ws_watchdog():
        while True:
            await asyncio.sleep(1)
            try:
                if websocket.client_state.name == "DISCONNECTED":
                    logger.info("ws_watchdog_disconnect", call_sid=ctx.call_sid)
                    guard.set_termination_source("ws_disconnect")
                    await task.queue_frame(EndFrame())
                    return
            except Exception:
                logger.info("ws_watchdog_disconnect_exception", call_sid=ctx.call_sid)
                guard.set_termination_source("ws_disconnect")
                await task.queue_frame(EndFrame())
                return

    watchdog_task = asyncio.create_task(ws_watchdog())

    try:
        await runner.run(task)
    finally:
        duration_task.cancel()
        watchdog_task.cancel()
        if comfort_noise:
            comfort_noise.stop()

    logger.info("pipeline_ended", call_sid=ctx.call_sid)

    return {
        "messages": context.messages,
        "greeting_text": greeting_text,
        "end_reason": guard.end_reason,
        "llm_end_reason": guard.llm_end_reason,
        "dnd_detected": guard.dnd_detected,
        "dnd_reason": guard.dnd_reason,
        "realtime_red_flags": guard.detected_red_flags,
        "termination_source": guard.termination_source,
    }


_INTEREST_RE = re.compile(r"INTEREST:\s*(high|medium|low)", re.IGNORECASE)


async def generate_call_summary(
    ctx: CallContext, messages: list[dict]
) -> tuple[str | None, str | None]:
    """
    Non-streaming Gemini call to summarize the conversation and classify interest.

    Returns (summary, interest_level). interest_level is "high"/"medium"/"low" or None.
    """
    # Normalize messages: may be Google Content objects or dicts
    def _normalize(m):
        if isinstance(m, dict):
            return m.get("role", ""), m.get("content", "")
        role = getattr(m, "role", "")
        parts = getattr(m, "parts", [])
        content = (parts[0].text or "") if parts and hasattr(parts[0], "text") else ""
        if role == "model":
            role = "assistant"
        return role, content

    conversation = [
        (role, content) for m in messages
        if (role := _normalize(m)[0]) in ("user", "assistant")
        and not (content := _normalize(m)[1]).startswith("[SYSTEM:")
    ]
    if not conversation:
        return None, None

    try:
        from google import genai

        client = genai.Client(api_key=gemini_key_pool.get_key())

        conv_text = "\n".join(f"{role.upper()}: {content}" for role, content in conversation)

        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="Analyze this phone conversation and provide:\n"
            "1. SUMMARY: A 2-3 sentence summary including the key outcome "
            "(e.g., confirmed attendance, requested callback, declined, no clear outcome). "
            "Be factual and concise.\n"
            "2. INTEREST: Classify the lead's interest level as high, medium, or low "
            "based on their actual engagement and intent expressed in the conversation.\n\n"
            "Format your response exactly as:\n"
            "SUMMARY: <your summary>\n"
            "INTEREST: <high|medium|low>\n\n"
            f"{conv_text}",
            config=genai.types.GenerateContentConfig(
                max_output_tokens=250,
                temperature=0.3,
            ),
        )
        raw = response.text.strip()

        # Parse interest level
        interest_match = _INTEREST_RE.search(raw)
        interest_level = interest_match.group(1).lower() if interest_match else None

        # Parse summary — everything after "SUMMARY:" up to "INTEREST:" (or end)
        summary = raw
        if "SUMMARY:" in raw.upper():
            after_summary = raw[raw.upper().index("SUMMARY:") + 8:]
            if "INTEREST:" in after_summary.upper():
                summary = after_summary[: after_summary.upper().index("INTEREST:")].strip()
            else:
                summary = after_summary.strip()

        logger.info(
            "call_summary_generated",
            call_sid=ctx.call_sid,
            summary_length=len(summary),
            interest_level=interest_level,
        )
        return summary, interest_level
    except Exception as e:
        logger.error("call_summary_generation_failed", call_sid=ctx.call_sid, error=str(e))
        return None, None
