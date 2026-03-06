"""
Plivo webhook and WebSocket routes.

- GET  /plivo/answer/{call_sid}  — returns Stream XML to connect call to WebSocket
- WS   /plivo/ws/{call_sid}      — Pipecat pipeline runs here
- POST /plivo/event/{call_sid}   — hangup/status callback from Plivo
"""

from __future__ import annotations

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
from app.pipeline.runner import generate_call_summary, run_pipeline
from app.plivo.xml_responses import build_hangup_xml, build_stream_xml

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo"])

# These are set during app startup (see main.py lifespan)
bot_config_loader: BotConfigLoader | None = None
ghl_client: GHLClient | None = None


def set_dependencies(loader: BotConfigLoader, ghl: GHLClient):
    global bot_config_loader, ghl_client
    bot_config_loader = loader
    ghl_client = ghl


# --- Helpers ---


async def _get_call_log(db: AsyncSession, call_sid: str) -> CallLog | None:
    result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
    return result.scalar_one_or_none()


async def _update_call_status(
    call_sid: str,
    *,
    status: str | None = None,
    outcome: str | None = None,
    summary: str | None = None,
    call_duration: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
):
    values: dict = {}
    if status is not None:
        values["status"] = status
    if outcome is not None:
        values["outcome"] = outcome
    if summary is not None:
        values["summary"] = summary
    if call_duration is not None:
        values["call_duration"] = call_duration
    if started_at is not None:
        values["started_at"] = started_at
    if ended_at is not None:
        values["ended_at"] = ended_at

    if not values:
        return

    async with get_db_session() as db:
        await db.execute(update(CallLog).where(CallLog.call_sid == call_sid).values(**values))
        await db.commit()


async def _post_ghl_outcome(
    ctx: CallContext,
    outcome: str,
    summary: str | None = None,
    error: str | None = None,
):
    if not ctx.ghl_webhook_url or ghl_client is None:
        return

    outcome_data = {
        "call_sid": ctx.call_sid,
        "ghl_contact_id": ctx.ghl_contact_id,
        "outcome": outcome,
        "contact_name": ctx.contact_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if summary:
        outcome_data["summary"] = summary
    if error:
        outcome_data["error"] = error

    await ghl_client.post_call_outcome(ctx.ghl_webhook_url, outcome_data)


def _map_plivo_status(plivo_status: str | None) -> str:
    """Map Plivo call status to our internal status."""
    mapping = {
        "completed": "completed",
        "busy": "no_answer",
        "failed": "failed",
        "timeout": "no_answer",
        "no-answer": "no_answer",
        "cancel": "failed",
        "machine": "voicemail",
    }
    return mapping.get(plivo_status or "", plivo_status or "unknown")


# --- Routes ---


@router.get("/answer/{call_sid}")
async def plivo_answer(call_sid: str, db: AsyncSession = Depends(get_db)):
    """Return Plivo XML to connect call to our WebSocket."""
    call_log = await _get_call_log(db, call_sid)
    if not call_log or not call_log.context_data:
        logger.warning("plivo_answer_no_context", call_sid=call_sid)
        return Response(content=build_hangup_xml(), media_type="application/xml")

    ws_url = f"wss://{settings.PUBLIC_HOST}/plivo/ws/{call_sid}"

    xml = build_stream_xml(
        websocket_url=ws_url,
        bidirectional=True,
        content_type="audio/x-l16;rate=16000",
        stream_timeout=3600,
        keep_call_alive=True,
    )
    logger.info("plivo_answer_stream_xml", call_sid=call_sid, ws_url=ws_url)
    return Response(content=xml, media_type="application/xml")


@router.websocket("/ws/{call_sid}")
async def plivo_websocket(websocket: WebSocket, call_sid: str):
    """WebSocket endpoint for Plivo audio streaming. Runs Pipecat pipeline."""
    await websocket.accept()

    # Load call context from Postgres
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    if not call_log or not call_log.context_data:
        logger.warning("plivo_ws_no_context", call_sid=call_sid)
        await websocket.close()
        return

    # Re-fetch full bot_config (includes Plivo creds, not stored in context_data)
    bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
    if not bot_config:
        logger.error("plivo_ws_bot_config_missing", call_sid=call_sid)
        await websocket.close()
        return

    ctx = CallContext.from_db(call_log, bot_config=bot_config)

    try:
        await _update_call_status(call_sid, status="in_progress", started_at=datetime.now(timezone.utc))
        logger.info("pipeline_call_started", call_sid=call_sid)

        # Run pipeline — returns conversation history
        conversation_messages = await run_pipeline(websocket, ctx, bot_config)

        # Generate LLM summary
        summary = await generate_call_summary(ctx, conversation_messages)

        # Update call log with outcome
        await _update_call_status(call_sid, outcome="completed", summary=summary)

        # Post outcome to GHL
        await _post_ghl_outcome(ctx, outcome="completed", summary=summary)

    except Exception as e:
        logger.error("pipeline_error", call_sid=call_sid, error=str(e))
        await _update_call_status(call_sid, status="error")
        await _post_ghl_outcome(ctx, outcome="error", error=str(e))


@router.post("/event/{call_sid}")
async def plivo_event(call_sid: str, request: Request):
    """Plivo hangup/status callback."""
    form = await request.form()
    call_status = form.get("CallStatus")
    duration = form.get("Duration")

    logger.info("plivo_event", call_sid=call_sid, status=call_status, duration=duration)

    mapped_status = _map_plivo_status(call_status)
    await _update_call_status(
        call_sid,
        status=mapped_status,
        call_duration=int(duration) if duration else None,
        ended_at=datetime.now(timezone.utc),
    )

    # Backup GHL outcome posting — if pipeline didn't post (e.g. crash)
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    if call_log and call_log.context_data and not call_log.outcome:
        bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
        if bot_config:
            ctx = CallContext.from_db(call_log, bot_config=bot_config)
            await _post_ghl_outcome(ctx, outcome=mapped_status)

    return {"status": "ok"}
