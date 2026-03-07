"""
Pipeline runner and post-call summary generation.

run_pipeline() starts and manages the Pipecat pipeline for a single call.
generate_call_summary() makes a non-streaming Gemini call to summarize the conversation
and classify the lead's interest level.
"""

from __future__ import annotations

import asyncio
import re

import structlog
from pipecat.frames.frames import EndFrame, LLMMessagesAppendFrame, TTSSpeakFrame
from pipecat.pipeline.runner import PipelineRunner
from starlette.websockets import WebSocket

from app.config import settings
from app.models.bot_config import BotConfig
from app.models.schemas import CallContext
from app.pipeline.factory import build_pipeline

logger = structlog.get_logger(__name__)


async def run_pipeline(
    websocket: WebSocket,
    ctx: CallContext,
    bot_config: BotConfig,
    provider: str = "plivo",
) -> dict:
    """
    Build and run the Pipecat pipeline for a single call.

    Returns dict with:
      - "messages": conversation message history (list of {role, content} dicts)
      - "recording_paths": (bot_wav, user_wav) tuple or None
    """
    task, transport, context, recorder, guard = await build_pipeline(bot_config, ctx, websocket, provider=provider)

    max_duration = getattr(bot_config, "max_call_duration", 480) or 480
    logger.info("pipeline_starting", call_sid=ctx.call_sid, voice=ctx.tts_voice, max_duration=max_duration)

    runner = PipelineRunner()

    # Send a fixed greeting directly via TTS (bypasses LLM — instant, no interruptions).
    greeting_text = f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"

    async def send_initial_greeting():
        await asyncio.sleep(0.5)
        await task.queue_frame(TTSSpeakFrame(text=greeting_text))
        logger.info("initial_greeting_triggered", call_sid=ctx.call_sid, greeting=greeting_text)

    asyncio.create_task(send_initial_greeting())

    # Max call duration enforcement
    async def enforce_max_duration():
        try:
            await asyncio.sleep(max_duration)
            logger.info("max_call_duration_reached", call_sid=ctx.call_sid, max_duration=max_duration)
            await task.queue_frame(EndFrame())
        except asyncio.CancelledError:
            pass

    duration_task = asyncio.create_task(enforce_max_duration())

    # Watchdog: detect WebSocket closure and stop pipeline
    async def ws_watchdog():
        """Monitor WebSocket state and cancel pipeline when connection drops."""
        while True:
            await asyncio.sleep(1)
            try:
                # Starlette WebSocket: client_state becomes DISCONNECTED on close
                if websocket.client_state.name == "DISCONNECTED":
                    logger.info("ws_watchdog_disconnect", call_sid=ctx.call_sid)
                    await task.queue_frame(EndFrame())
                    return
            except Exception:
                logger.info("ws_watchdog_disconnect_exception", call_sid=ctx.call_sid)
                await task.queue_frame(EndFrame())
                return

    watchdog_task = asyncio.create_task(ws_watchdog())

    try:
        await runner.run(task)
    finally:
        duration_task.cancel()
        watchdog_task.cancel()
        if recorder:
            recorder.close_wav()

    logger.info("pipeline_ended", call_sid=ctx.call_sid)

    return {
        "messages": context.messages,
        "recording_paths": recorder.get_recording_paths() if recorder else None,
        "end_reason": guard.end_reason,
        "dnd_detected": guard.dnd_detected,
        "dnd_reason": guard.dnd_reason,
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
        content = parts[0].text if parts and hasattr(parts[0], "text") else ""
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

        client = genai.Client(api_key=settings.GOOGLE_AI_API_KEY)

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
