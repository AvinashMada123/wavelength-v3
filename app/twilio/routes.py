"""
Twilio webhook and WebSocket routes.

- POST /twilio/answer/{call_sid}  — returns TwiML to connect call to WebSocket
- WS   /twilio/ws/{call_sid}      — Pipecat pipeline runs here
- POST /twilio/event/{call_sid}   — status callback from Twilio
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_config.loader import BotConfigLoader
from app.config import settings
from app.database import get_db, get_db_session
from app.ghl.client import GHLClient
from app.models.call_log import CallLog
from app.models.schemas import CallContext
from app.pipeline import session_limiter
from app.pipeline.runner import generate_call_summary, run_pipeline
from app.plivo.routes import (
    _compute_agent_word_share,
    _get_call_log,
    _post_ghl_outcome,
    _run_ghl_workflows,
    _save_call_analytics,
    _update_call_status,
)
from app.services.call_analyzer import CallAnalyzer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/twilio", tags=["twilio"])

# Set during app startup (see main.py lifespan)
bot_config_loader: BotConfigLoader | None = None
ghl_client: GHLClient | None = None


def set_dependencies(loader: BotConfigLoader, ghl: GHLClient):
    global bot_config_loader, ghl_client
    bot_config_loader = loader
    ghl_client = ghl


# --- Routes ---


@router.post("/answer/{call_sid}")
async def twilio_answer(call_sid: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Return TwiML to connect call to our WebSocket via <Stream>."""
    call_log = await _get_call_log(db, call_sid)
    if not call_log or not call_log.context_data:
        logger.warning("twilio_answer_no_context", call_sid=call_sid)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="application/xml",
        )

    # Store the Twilio CallSid from the POST body for later use
    form = await request.form()
    twilio_call_sid = form.get("CallSid", "")
    if twilio_call_sid:
        async with get_db_session() as sess:
            await sess.execute(
                update(CallLog)
                .where(CallLog.call_sid == call_sid)
                .values(plivo_call_uuid=twilio_call_sid)
            )
            await sess.commit()

    ws_url = f"wss://{settings.PUBLIC_HOST}/twilio/ws/{call_sid}"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{ws_url}" />'
        "</Connect>"
        "</Response>"
    )
    logger.info("twilio_answer_twiml", call_sid=call_sid, ws_url=ws_url)
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/ws/{call_sid}")
async def twilio_websocket(websocket: WebSocket, call_sid: str):
    """WebSocket endpoint for Twilio audio streaming. Runs Pipecat pipeline."""
    await websocket.accept()

    # Load call context from Postgres
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    if not call_log or not call_log.context_data:
        logger.warning("twilio_ws_no_context", call_sid=call_sid)
        await websocket.close()
        return

    bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
    if not bot_config:
        logger.error("twilio_ws_bot_config_missing", call_sid=call_sid)
        await websocket.close()
        return

    ctx = CallContext.from_db(call_log, bot_config=bot_config)

    # Enforce concurrent session limit
    if not await session_limiter.acquire():
        logger.warning("session_limit_rejected", call_sid=call_sid)
        await _update_call_status(call_sid, status="failed", outcome="capacity_exceeded")
        await websocket.close()
        return

    try:
        await _update_call_status(call_sid, status="in_progress", started_at=datetime.now(timezone.utc))
        logger.info("twilio_pipeline_call_started", call_sid=call_sid)

        # Pre-read Twilio's 'start' event to get the stream SID
        stream_sid = ""
        try:
            for _ in range(5):  # Twilio sends 'connected' then 'start'
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                event = msg.get("event", "")
                if event == "start":
                    stream_sid = msg.get("streamSid", "")
                    logger.info("twilio_stream_sid_captured", call_sid=call_sid, stream_sid=stream_sid)
                    break
        except Exception as e:
            logger.error("twilio_stream_sid_read_failed", call_sid=call_sid, error=str(e))

        # Run pre-call GHL workflows
        await _run_ghl_workflows(ctx, bot_config, "pre_call")

        # Run pipeline (provider="twilio" tells factory to use TwilioFrameSerializer)
        pipeline_result = await run_pipeline(websocket, ctx, bot_config, provider="twilio", stream_sid=stream_sid)
        conversation_messages = pipeline_result["messages"]
        end_reason = pipeline_result.get("end_reason")
        dnd_detected = pipeline_result.get("dnd_detected", False)
        dnd_reason = pipeline_result.get("dnd_reason")

        # If voicemail or hold/IVR detected, short-circuit
        if end_reason in ("voicemail", "hold_ivr"):
            await _update_call_status(call_sid, outcome=end_reason, metadata={"end_reason": end_reason})
            await _post_ghl_outcome(ctx, outcome=end_reason)
            return

        # Build transcript entries
        def _extract_message(m):
            if isinstance(m, dict):
                role = m.get("role", "")
                content = m.get("content", "")
            else:
                role = getattr(m, "role", "")
                parts = getattr(m, "parts", [])
                content = parts[0].text if parts and hasattr(parts[0], "text") else ""
                if role == "model":
                    role = "assistant"
            if role in ("user", "assistant") and not content.startswith("[SYSTEM:"):
                return {"role": role, "content": content}
            return None

        transcript_entries = [e for m in conversation_messages if (e := _extract_message(m)) is not None]
        # Filter empty / punctuation-only entries (STT noise)
        transcript_entries = [
            e for e in transcript_entries
            if e["content"].strip().strip(".,;:!?-")
        ]

        # Prepend greeting (sent via TTSSpeakFrame, bypasses context aggregator).
        greeting_text = pipeline_result.get("greeting_text") or (
            f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"
        )
        # Remove LLM's duplicate greeting echo
        transcript_entries = [
            e for e in transcript_entries
            if not (e["role"] == "assistant" and bot_config.agent_name in e["content"][:60] and "calling from" in e["content"][:80])
        ]
        transcript_entries.insert(0, {"role": "assistant", "content": greeting_text})

        # Generate analysis — goal-aware if configured, generic fallback otherwise
        goal_cfg = getattr(bot_config, "goal_config", None)
        if isinstance(goal_cfg, str):
            import json as _json
            goal_cfg = _json.loads(goal_cfg)
        summary = None
        interest_level = None
        analysis = None

        try:
            analyzer = CallAnalyzer()
            analysis = await analyzer.analyze(
                transcript=transcript_entries,
                goal_config=goal_cfg,
                system_prompt=ctx.filled_prompt,
                realtime_red_flags=pipeline_result.get("realtime_red_flags", []),
                call_sid=call_sid,
            )
            summary = analysis.summary
            interest_level = analysis.interest_level
        except Exception as e:
            logger.error("twilio_post_call_analysis_failed", call_sid=call_sid, error=str(e))
            try:
                summary, interest_level = await generate_call_summary(ctx, conversation_messages)
            except Exception:
                pass

        # Recording: Twilio has its own native recording — not implemented yet
        turn_count = sum(1 for t in transcript_entries if t["role"] == "user")
        call_metadata = {
            "transcript": transcript_entries,
            "interest_level": interest_level,
            "call_metrics": {"turn_count": turn_count},
        }
        if dnd_detected:
            call_metadata["dnd_detected"] = True
            call_metadata["dnd_reason"] = dnd_reason
        if end_reason:
            call_metadata["end_reason"] = end_reason

        # Add goal-based analytics to metadata if available
        if analysis and analysis.goal_outcome:
            call_metadata["goal_outcome"] = analysis.goal_outcome
            call_metadata["red_flags"] = [rf.model_dump() for rf in analysis.red_flags]
            call_metadata["captured_data"] = analysis.captured_data

        await _update_call_status(call_sid, outcome="completed", summary=summary, metadata=call_metadata)
        await _post_ghl_outcome(ctx, outcome="completed", summary=summary, metadata=call_metadata)
        await _run_ghl_workflows(ctx, bot_config, "post_call")

        # Write to call_analytics table if goal-based analysis was performed
        if analysis and analysis.goal_outcome is not None and goal_cfg:
            try:
                async with get_db_session() as db:
                    existing_log = await _get_call_log(db, call_sid)
                await _save_call_analytics(
                    call_sid=call_sid,
                    bot_id=bot_config.id,
                    call_log_id=existing_log.id if existing_log else None,
                    analysis=analysis,
                    goal_type=goal_cfg.get("goal_type") if isinstance(goal_cfg, dict) else goal_cfg.goal_type,
                    turn_count=turn_count,
                    call_duration=existing_log.call_duration if existing_log else None,
                    transcript=transcript_entries,
                    org_id=bot_config.org_id,
                )
            except Exception as e:
                logger.error("twilio_save_analytics_failed", call_sid=call_sid, error=str(e))

    except Exception as e:
        logger.error("twilio_pipeline_error", call_sid=call_sid, error=str(e))
        await _update_call_status(call_sid, status="error")
        await _post_ghl_outcome(ctx, outcome="error", error=str(e))
        # Record pipeline failure in circuit breaker
        try:
            from app.services import circuit_breaker
            async with get_db_session() as db:
                tripped = await circuit_breaker.record_failure(
                    db, bot_config.id, f"pipeline_error: {str(e)[:200]}"
                )
                if tripped:
                    logger.warning("circuit_breaker_tripped_by_pipeline", bot_id=str(bot_config.id))
        except Exception:
            logger.error("circuit_breaker_record_failed", call_sid=call_sid, exc_info=True)
    finally:
        await session_limiter.release()


@router.post("/event/{call_sid}")
async def twilio_event(call_sid: str, request: Request):
    """Twilio status callback."""
    form = await request.form()
    call_status = form.get("CallStatus", "")
    duration = form.get("CallDuration", form.get("Duration"))

    logger.info("twilio_event", call_sid=call_sid, status=call_status, duration=duration)

    # Only process terminal statuses
    if call_status not in ("completed", "busy", "no-answer", "canceled", "failed"):
        return {"status": "ok"}

    mapped_status = _map_twilio_status(call_status)
    duration_val = int(duration) if duration else None
    await _update_call_status(
        call_sid,
        status=mapped_status,
        call_duration=duration_val,
        ended_at=datetime.now(timezone.utc),
    )

    # Update metadata with actual duration
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    if call_log and call_log.metadata_ and duration_val:
        updated_meta = dict(call_log.metadata_)
        updated_meta.setdefault("call_metrics", {})["total_duration_s"] = duration_val
        await _update_call_status(call_sid, metadata=updated_meta)

    # Backup GHL outcome posting (if pipeline didn't post)
    if call_log and call_log.context_data and not call_log.outcome:
        bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
        if bot_config:
            ctx = CallContext.from_db(call_log, bot_config=bot_config)
            await _post_ghl_outcome(ctx, outcome=mapped_status)

    return {"status": "ok"}


def _map_twilio_status(twilio_status: str) -> str:
    """Map Twilio call status to internal status."""
    mapping = {
        "completed": "completed",
        "busy": "no_answer",
        "no-answer": "no_answer",
        "canceled": "failed",
        "failed": "failed",
    }
    return mapping.get(twilio_status, twilio_status or "unknown")
