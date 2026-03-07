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
from pipecat.frames.frames import LLMMessagesAppendFrame, TTSSpeakFrame
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
) -> dict:
    """
    Build and run the Pipecat pipeline for a single call.

    Returns dict with:
      - "messages": conversation message history (list of {role, content} dicts)
      - "recording_paths": (bot_wav, user_wav) tuple or None
    """
    task, transport, context, serializer = await build_pipeline(bot_config, ctx, websocket)

    logger.info("pipeline_starting", call_sid=ctx.call_sid, voice=ctx.tts_voice)

    runner = PipelineRunner()

    # Send a fixed greeting directly via TTS (bypasses LLM — instant, no interruptions).
    greeting_text = f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"

    async def send_initial_greeting():
        await asyncio.sleep(0.5)
        await task.queue_frame(TTSSpeakFrame(text=greeting_text))
        logger.info("initial_greeting_triggered", call_sid=ctx.call_sid, greeting=greeting_text)

    asyncio.create_task(send_initial_greeting())

    # Watchdog: detect WebSocket closure and stop pipeline
    async def ws_watchdog():
        """Monitor WebSocket state and cancel pipeline when connection drops."""
        from pipecat.frames.frames import EndFrame
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
        watchdog_task.cancel()
        serializer.close_wav()

    logger.info("pipeline_ended", call_sid=ctx.call_sid)

    return {
        "messages": context.messages,
        "recording_paths": serializer.get_recording_paths(),
    }


_INTEREST_RE = re.compile(r"INTEREST:\s*(high|medium|low)", re.IGNORECASE)


async def generate_call_summary(
    ctx: CallContext, messages: list[dict]
) -> tuple[str | None, str | None]:
    """
    Non-streaming Gemini call to summarize the conversation and classify interest.

    Returns (summary, interest_level). interest_level is "high"/"medium"/"low" or None.
    """
    conversation = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not conversation:
        return None, None

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_AI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)

        response = await model.generate_content_async(
            "Analyze this phone conversation and provide:\n"
            "1. SUMMARY: A 2-3 sentence summary including the key outcome "
            "(e.g., confirmed attendance, requested callback, declined, no clear outcome). "
            "Be factual and concise.\n"
            "2. INTEREST: Classify the lead's interest level as high, medium, or low "
            "based on their actual engagement and intent expressed in the conversation.\n\n"
            "Format your response exactly as:\n"
            "SUMMARY: <your summary>\n"
            "INTEREST: <high|medium|low>\n\n"
            f"{conv_text}",
            generation_config={"max_output_tokens": 250, "temperature": 0.3},
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
