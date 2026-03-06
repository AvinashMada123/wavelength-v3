"""
Pipeline runner and post-call summary generation.

run_pipeline() starts and manages the Pipecat pipeline for a single call.
generate_call_summary() makes a non-streaming Gemini call to summarize the conversation.
"""

from __future__ import annotations

import asyncio

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
) -> list[dict]:
    """
    Build and run the Pipecat pipeline for a single call.

    Returns the conversation message history (list of {role, content} dicts)
    for post-call summary generation.
    """
    task, transport, context = await build_pipeline(bot_config, ctx, websocket)

    logger.info("pipeline_starting", call_sid=ctx.call_sid, voice=ctx.tts_voice)

    runner = PipelineRunner()

    # Send a fixed greeting directly via TTS (bypasses LLM — instant, no interruptions).
    # The greeting text is derived from the bot config's prompt template.
    greeting_text = f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"

    async def send_initial_greeting():
        await asyncio.sleep(0.5)
        await task.queue_frame(TTSSpeakFrame(text=greeting_text))
        logger.info("initial_greeting_triggered", call_sid=ctx.call_sid, greeting=greeting_text)

    asyncio.create_task(send_initial_greeting())

    await runner.run(task)

    logger.info("pipeline_ended", call_sid=ctx.call_sid)

    return context.messages


async def generate_call_summary(ctx: CallContext, messages: list[dict]) -> str | None:
    """
    Non-streaming Gemini call to summarize the conversation.
    Called OUTSIDE the pipeline in the WebSocket handler's cleanup phase.
    """
    # Filter to only user/assistant messages (skip system prompt)
    conversation = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not conversation:
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_AI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)

        response = await model.generate_content_async(
            f"Summarize this phone conversation in 2-3 sentences. "
            f"Include the key outcome (e.g., confirmed attendance, requested callback, "
            f"declined, no clear outcome). Be factual and concise.\n\n{conv_text}",
            generation_config={"max_output_tokens": 150, "temperature": 0.3},
        )
        summary = response.text.strip()
        logger.info("call_summary_generated", call_sid=ctx.call_sid, summary_length=len(summary))
        return summary
    except Exception as e:
        logger.error("call_summary_generation_failed", call_sid=ctx.call_sid, error=str(e))
        return None
