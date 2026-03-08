"""
Plivo webhook and WebSocket routes.

- GET  /plivo/answer/{call_sid}  — returns Stream XML to connect call to WebSocket
- WS   /plivo/ws/{call_sid}      — Pipecat pipeline runs here
- POST /plivo/event/{call_sid}   — hangup/status callback from Plivo
"""

from __future__ import annotations

import asyncio
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
from app.pipeline import session_limiter
from app.models.call_log import CallLog
from app.models.schemas import CallContext
from app.models.call_analytics import CallAnalytics
from app.models.schemas import CallAnalysis
from app.pipeline.runner import generate_call_summary, run_pipeline
from app.services.call_analyzer import CallAnalyzer
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
        if metadata.get("recording_url"):
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
    if isinstance(workflows, str):
        import json
        try:
            workflows = json.loads(workflows)
        except (json.JSONDecodeError, TypeError):
            workflows = []

    # Filter enabled workflows for this timing
    active = [wf for wf in workflows if isinstance(wf, dict) and wf.get("timing") == timing and wf.get("enabled") and wf.get("tag")]
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


def _compute_agent_word_share(transcript: list[dict]) -> float:
    """Ratio of bot words to total words. Proxy for talk time."""
    bot_words = sum(len(t["content"].split()) for t in transcript if t["role"] == "assistant")
    user_words = sum(len(t["content"].split()) for t in transcript if t["role"] == "user")
    total = bot_words + user_words
    return round(bot_words / total, 2) if total > 0 else 0.0


def _get_max_severity(red_flags: list) -> str | None:
    """Return the highest severity from a list of red flags."""
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    if not red_flags:
        return None
    severities = [rf.get("severity", rf.severity if hasattr(rf, "severity") else "low") for rf in red_flags]
    return min(severities, key=lambda s: severity_order.get(s, 99))


async def _save_call_analytics(
    call_sid: str,
    bot_id,
    call_log_id,
    analysis: CallAnalysis,
    goal_type: str,
    turn_count: int,
    call_duration: int | None,
    transcript: list[dict],
) -> None:
    """Write a CallAnalytics row after goal-based analysis."""
    red_flags_dicts = [rf.model_dump() for rf in analysis.red_flags]
    has_flags = len(red_flags_dicts) > 0
    max_severity = _get_max_severity(red_flags_dicts) if has_flags else None

    row = CallAnalytics(
        call_log_id=call_log_id,
        bot_id=bot_id,
        goal_type=goal_type,
        goal_outcome=analysis.goal_outcome,
        has_red_flags=has_flags,
        red_flag_max_severity=max_severity,
        red_flags=red_flags_dicts if has_flags else None,
        captured_data=analysis.captured_data or None,
        turn_count=turn_count,
        call_duration_secs=call_duration,
        agent_word_share=_compute_agent_word_share(transcript),
    )

    async with get_db_session() as db:
        db.add(row)
        await db.commit()

    logger.info(
        "call_analytics_saved",
        call_sid=call_sid,
        goal_outcome=analysis.goal_outcome,
        has_red_flags=has_flags,
        max_severity=max_severity,
    )

    # If critical/high red flags, post alert to GHL webhook
    if has_flags and max_severity in ("critical", "high"):
        logger.info("red_flag_alert_triggered", call_sid=call_sid, severity=max_severity)


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
    recording_cb = f"{settings.PUBLIC_BASE_URL}/plivo/recording/{call_sid}"

    xml = build_stream_xml(
        websocket_url=ws_url,
        bidirectional=True,
        content_type="audio/x-l16;rate=16000",
        stream_timeout=3600,
        keep_call_alive=True,
        recording_callback_url=recording_cb,
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

    # Enforce concurrent session limit
    if not await session_limiter.acquire():
        logger.warning("session_limit_rejected", call_sid=call_sid)
        await _update_call_status(call_sid, status="failed", outcome="capacity_exceeded")
        await websocket.close()
        return

    try:
        await _update_call_status(call_sid, status="in_progress", started_at=datetime.now(timezone.utc))
        logger.info("pipeline_call_started", call_sid=call_sid)

        # Run pre-call GHL workflows (tag contacts before call starts)
        await _run_ghl_workflows(ctx, bot_config, "pre_call")

        # Run pipeline — returns conversation history + recording paths + guard results
        pipeline_result = await run_pipeline(websocket, ctx, bot_config)
        conversation_messages = pipeline_result["messages"]
        end_reason = pipeline_result.get("end_reason")
        dnd_detected = pipeline_result.get("dnd_detected", False)
        dnd_reason = pipeline_result.get("dnd_reason")
        logger.info("post_call_pipeline_done", call_sid=call_sid, msg_count=len(conversation_messages),
                     end_reason=end_reason, dnd=dnd_detected)

        # If voicemail or hold/IVR detected, short-circuit post-call processing
        if end_reason in ("voicemail", "hold_ivr"):
            await _update_call_status(call_sid, outcome=end_reason, metadata={"end_reason": end_reason})
            await _post_ghl_outcome(ctx, outcome=end_reason)
            return

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
                content = (parts[0].text or "") if parts and hasattr(parts[0], "text") else ""
                if role == "model":
                    role = "assistant"
            if role in ("user", "assistant") and not content.startswith("[SYSTEM:"):
                return {"role": role, "content": content}
            return None

        # Log raw messages for debugging transcript issues
        for i, m in enumerate(conversation_messages):
            if isinstance(m, dict):
                logger.info("raw_ctx_message", idx=i, role=m.get("role"), preview=m.get("content", "")[:100])
            else:
                role = getattr(m, "role", "?")
                parts = getattr(m, "parts", [])
                text = (parts[0].text or "")[:100] if parts and hasattr(parts[0], "text") else "?"
                logger.info("raw_ctx_message", idx=i, role=role, preview=text)

        transcript_entries = [e for m in conversation_messages if (e := _extract_message(m)) is not None]
        # Filter system prompt (may be stored as "user" or "system" role by Google)
        # Actual content is filled_prompt + _CONVERSATION_RULES, so use startswith
        transcript_entries = [
            e for e in transcript_entries
            if not e["content"].startswith(ctx.filled_prompt[:200])
        ]

        # Prepend greeting (sent via TTSSpeakFrame, bypasses context aggregator)
        greeting_text = f"Hi {ctx.contact_name}, this is {bot_config.agent_name} calling from {bot_config.company_name}. How are you doing today?"
        # Remove LLM's duplicate greeting echo
        transcript_entries = [
            e for e in transcript_entries
            if not (e["role"] == "assistant" and bot_config.agent_name in e["content"][:60] and "calling from" in e["content"][:80])
        ]
        transcript_entries.insert(0, {"role": "assistant", "content": greeting_text})
        logger.info("post_call_transcript_built", call_sid=call_sid, entries=len(transcript_entries))

        # Generate analysis — goal-aware if configured, generic fallback otherwise
        goal_cfg = getattr(bot_config, "goal_config", None)
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
            logger.info(
                "post_call_analysis_done",
                call_sid=call_sid,
                goal_outcome=analysis.goal_outcome,
                interest=interest_level,
                red_flags=len(analysis.red_flags),
                summary_len=len(summary) if summary else 0,
            )
        except Exception as e:
            logger.error("post_call_analysis_failed", call_sid=call_sid, error=str(e), exc_info=True)
            # Fallback to legacy summary if analyzer fails
            try:
                summary, interest_level = await generate_call_summary(ctx, conversation_messages)
            except Exception:
                pass

        # Build metadata — merge with existing to preserve recording_url from Plivo callback
        async with get_db_session() as db:
            existing_log = await _get_call_log(db, call_sid)
        existing_meta = dict(existing_log.metadata_) if existing_log and existing_log.metadata_ else {}

        turn_count = sum(1 for t in transcript_entries if t["role"] == "user")
        existing_meta.update({
            "transcript": transcript_entries,
            "interest_level": interest_level,
            "call_metrics": {"turn_count": turn_count},
        })
        if dnd_detected:
            existing_meta["dnd_detected"] = True
            existing_meta["dnd_reason"] = dnd_reason
        if end_reason:
            existing_meta["end_reason"] = end_reason

        # Add goal-based analytics to metadata if available
        if analysis and analysis.goal_outcome:
            existing_meta["goal_outcome"] = analysis.goal_outcome
            existing_meta["red_flags"] = [rf.model_dump() for rf in analysis.red_flags]
            existing_meta["captured_data"] = analysis.captured_data

        # Update call log with outcome + metadata
        await _update_call_status(
            call_sid, status="completed", outcome="completed", summary=summary, metadata=existing_meta
        )
        logger.info("post_call_metadata_saved", call_sid=call_sid, turns=turn_count)

        # Write to call_analytics table if goal-based analysis was performed
        if analysis and analysis.goal_outcome and goal_cfg:
            try:
                await _save_call_analytics(
                    call_sid=call_sid,
                    bot_id=bot_config.id,
                    call_log_id=existing_log.id if existing_log else None,
                    analysis=analysis,
                    goal_type=goal_cfg.get("goal_type") if isinstance(goal_cfg, dict) else goal_cfg.goal_type,
                    turn_count=turn_count,
                    call_duration=existing_log.call_duration if existing_log else None,
                    transcript=transcript_entries,
                )
            except Exception as e:
                logger.error("save_call_analytics_failed", call_sid=call_sid, error=str(e), exc_info=True)

        # Post enriched outcome to GHL (failures here should not mark call as error)
        try:
            await _post_ghl_outcome(
                ctx, outcome="completed", summary=summary, metadata=existing_meta
            )
            await _run_ghl_workflows(ctx, bot_config, "post_call")
        except Exception as e:
            logger.error("post_call_ghl_error", call_sid=call_sid, error=str(e), exc_info=True)

    except Exception as e:
        logger.error("pipeline_error", call_sid=call_sid, error=str(e), exc_info=True)
        await _update_call_status(call_sid, status="error")
        await _post_ghl_outcome(ctx, outcome="error", error=str(e))
    finally:
        await session_limiter.release()


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


@router.post("/recording/{call_sid}")
async def plivo_recording_callback(call_sid: str, request: Request):
    """Plivo recording callback — receives recording URL when call recording is ready."""
    form = await request.form()
    record_url = form.get("RecordUrl")
    recording_id = form.get("RecordingID")
    recording_duration = form.get("RecordingDuration")
    recording_duration_ms = form.get("RecordingDurationMs")

    logger.info(
        "plivo_recording_callback",
        call_sid=call_sid,
        record_url=record_url,
        recording_id=recording_id,
        duration=recording_duration,
    )

    if not record_url:
        logger.warning("plivo_recording_callback_no_url", call_sid=call_sid)
        return {"status": "ok"}

    # Race-safe merge: read existing metadata, merge recording fields
    async with get_db_session() as db:
        call_log = await _get_call_log(db, call_sid)

    existing_meta = dict(call_log.metadata_) if call_log and call_log.metadata_ else {}
    existing_meta["recording_url"] = record_url
    existing_meta["recording_id"] = recording_id
    if recording_duration_ms:
        existing_meta["recording_duration_ms"] = int(recording_duration_ms)
    elif recording_duration:
        existing_meta["recording_duration_ms"] = int(float(recording_duration) * 1000)

    await _update_call_status(call_sid, metadata=existing_meta)
    logger.info("plivo_recording_saved", call_sid=call_sid, recording_id=recording_id)

    return {"status": "ok"}
