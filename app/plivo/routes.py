"""
Plivo webhook and WebSocket routes.

- GET  /plivo/answer/{call_sid}  — returns Stream XML to connect call to WebSocket
- WS   /plivo/ws/{call_sid}      — Pipecat pipeline runs here
- POST /plivo/event/{call_sid}   — hangup/status callback from Plivo
"""

from __future__ import annotations

import asyncio
import wave
from datetime import datetime, timezone
from pathlib import Path

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
    metadata: dict | None = None,
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
    if metadata is not None:
        values["metadata_"] = metadata

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
    metadata: dict | None = None,
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
    if metadata:
        outcome_data["interest_level"] = metadata.get("interest_level")
        outcome_data["call_metrics"] = metadata.get("call_metrics")
        # Transcript excluded from webhook (payload size risk) — available via API
        if metadata.get("recording_path"):
            outcome_data["recording_url"] = (
                f"{settings.PUBLIC_BASE_URL}/api/calls/{ctx.call_sid}/recording"
            )

    await ghl_client.post_call_outcome(ctx.ghl_webhook_url, outcome_data)


async def _run_ghl_workflows(ctx: CallContext, bot_config, timing: str) -> None:
    """Run GHL workflows matching the given timing (pre_call / post_call)."""
    if not bot_config:
        return
    api_key = getattr(bot_config, "ghl_api_key", None)
    location_id = getattr(bot_config, "ghl_location_id", None)
    workflows = getattr(bot_config, "ghl_workflows", None) or []

    # Filter enabled workflows for this timing
    active = [wf for wf in workflows if wf.get("timing") == timing and wf.get("enabled") and wf.get("tag")]
    if not active or not api_key or not location_id:
        return

    # Resolve contact_id (from call context or phone lookup)
    contact_id = ctx.ghl_contact_id
    if not contact_id:
        from app.ghl.client import GHLClient

        bot_ghl = GHLClient(api_key=api_key)
        try:
            async with get_db_session() as db:
                call_log = await _get_call_log(db, ctx.call_sid)
            phone = call_log.contact_phone if call_log else None
            if not phone:
                return
            contact_id = await bot_ghl.find_contact(location_id, phone)
        finally:
            await bot_ghl.close()

    if not contact_id:
        logger.warning("ghl_workflows_skipped_no_contact", call_sid=ctx.call_sid, timing=timing)
        return

    # Apply tags
    from app.ghl.client import GHLClient

    bot_ghl = GHLClient(api_key=api_key)
    try:
        for wf in active:
            tag = wf["tag"]
            ok = await bot_ghl.tag_contact(contact_id, tag)
            logger.info(
                "ghl_workflow_executed",
                call_sid=ctx.call_sid,
                workflow=wf.get("name", wf.get("id", "?")),
                tag=tag,
                success=ok,
            )
    finally:
        await bot_ghl.close()


def _merge_recording_sync(bot_wav_path: str, user_wav_path: str, output_path: str) -> bool:
    """Mix bot + user mono WAVs into a single mono WAV. Runs in executor."""
    try:
        import struct

        with wave.open(bot_wav_path, "rb") as bf:
            bot_data = bf.readframes(bf.getnframes())
        with wave.open(user_wav_path, "rb") as uf:
            user_data = uf.readframes(uf.getnframes())

        # Pad shorter track to match longer (16-bit = 2 bytes per sample)
        max_len = max(len(bot_data), len(user_data))
        bot_data = bot_data.ljust(max_len, b"\x00")
        user_data = user_data.ljust(max_len, b"\x00")

        # Mix: add samples and clamp to int16 range
        n_samples = max_len // 2
        bot_samples = struct.unpack(f"<{n_samples}h", bot_data[:n_samples * 2])
        user_samples = struct.unpack(f"<{n_samples}h", user_data[:n_samples * 2])
        mixed = struct.pack(
            f"<{n_samples}h",
            *(max(-32768, min(32767, b + u)) for b, u in zip(bot_samples, user_samples)),
        )

        with wave.open(output_path, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(mixed)

        return True
    except Exception:
        logger.error("recording_merge_failed", exc_info=True)
        return False


async def _merge_recording(bot_wav: str, user_wav: str, call_sid: str) -> str | None:
    """Merge bot + user WAVs into stereo. Keeps mono files for debugging."""
    output_path = f"recordings/{call_sid}.wav"
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, _merge_recording_sync, bot_wav, user_wav, output_path)
    if ok:
        logger.info("recording_merged", call_sid=call_sid, path=output_path)
        return output_path
    return None


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

        # Run pre-call GHL workflows (tag contacts before call starts)
        await _run_ghl_workflows(ctx, bot_config, "pre_call")

        # Run pipeline — returns conversation history + recording paths
        pipeline_result = await run_pipeline(websocket, ctx, bot_config)
        conversation_messages = pipeline_result["messages"]
        recording_paths = pipeline_result["recording_paths"]
        logger.info("post_call_pipeline_done", call_sid=call_sid, msg_count=len(conversation_messages), recording_paths=recording_paths)

        # Build transcript entries (filter system messages and system prompt)
        # context.messages may be Google Content objects (with .role/.parts) or dicts
        def _extract_message(m) -> dict | None:
            if isinstance(m, dict):
                role = m.get("role", "")
                content = m.get("content", "")
            else:
                # Google Content object: .role is "user"/"model", .parts[0].text
                role = getattr(m, "role", "")
                parts = getattr(m, "parts", [])
                content = parts[0].text if parts and hasattr(parts[0], "text") else ""
                if role == "model":
                    role = "assistant"
            if role in ("user", "assistant") and not content.startswith("[SYSTEM:"):
                return {"role": role, "content": content}
            return None

        transcript_entries = [e for m in conversation_messages if (e := _extract_message(m)) is not None]
        # First message is always the system prompt injected as "user" role — skip it
        if transcript_entries and transcript_entries[0]["role"] == "user" and transcript_entries[0]["content"] == ctx.filled_prompt:
            transcript_entries = transcript_entries[1:]

        # Prepend greeting (sent via TTSSpeakFrame, bypasses context aggregator)
        greeting_text = f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"
        transcript_entries.insert(0, {"role": "assistant", "content": greeting_text})
        logger.info("post_call_transcript_built", call_sid=call_sid, entries=len(transcript_entries))

        # Generate LLM summary + interest classification
        try:
            summary, interest_level = await generate_call_summary(ctx, conversation_messages)
            logger.info("post_call_summary_done", call_sid=call_sid, interest=interest_level, summary_len=len(summary) if summary else 0)
        except Exception as e:
            logger.error("post_call_summary_failed", call_sid=call_sid, error=str(e), exc_info=True)
            summary, interest_level = None, None

        # Merge recording (runs in executor)
        recording_path = None
        if recording_paths:
            try:
                recording_path = await _merge_recording(*recording_paths, call_sid)
                logger.info("post_call_recording_merged", call_sid=call_sid, path=recording_path)
            except Exception as e:
                logger.error("post_call_recording_failed", call_sid=call_sid, error=str(e), exc_info=True)

        # Build metadata
        turn_count = sum(1 for t in transcript_entries if t["role"] == "user")
        call_metadata = {
            "transcript": transcript_entries,
            "interest_level": interest_level,
            "call_metrics": {"turn_count": turn_count},
        }
        if recording_path:
            call_metadata["recording_path"] = recording_path

        # Update call log with outcome + metadata
        await _update_call_status(
            call_sid, outcome="completed", summary=summary, metadata=call_metadata
        )
        logger.info("post_call_metadata_saved", call_sid=call_sid, turns=turn_count, has_recording=bool(recording_path))

        # Post enriched outcome to GHL
        await _post_ghl_outcome(
            ctx, outcome="completed", summary=summary, metadata=call_metadata
        )

        # Run post-call GHL workflows (tag contacts)
        await _run_ghl_workflows(ctx, bot_config, "post_call")

    except Exception as e:
        logger.error("pipeline_error", call_sid=call_sid, error=str(e), exc_info=True)
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
    duration_val = int(duration) if duration else None
    await _update_call_status(
        call_sid,
        status=mapped_status,
        call_duration=duration_val,
        ended_at=datetime.now(timezone.utc),
    )

    # Update metadata with actual duration from Plivo
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    if call_log and call_log.metadata_ and duration_val:
        updated_meta = dict(call_log.metadata_)
        updated_meta.setdefault("call_metrics", {})["total_duration_s"] = duration_val
        await _update_call_status(call_sid, metadata=updated_meta)

    # Backup GHL outcome posting — if pipeline didn't post (e.g. crash)
    if call_log and call_log.context_data and not call_log.outcome:
        bot_config = await bot_config_loader.get(call_log.context_data["bot_id"])
        if bot_config:
            ctx = CallContext.from_db(call_log, bot_config=bot_config)
            await _post_ghl_outcome(ctx, outcome=mapped_status)

    return {"status": "ok"}
