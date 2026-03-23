"""CRUD API for bot configurations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_org
from app.bot_config.loader import BotConfigLoader
from app.database import get_db
from app.models.bot_config import BotConfig
from app.models.schemas import BotConfigResponse, CreateBotConfigRequest, GoalConfig, UpdateBotConfigRequest
from app.models.user import User

# Providers restricted to super_admin only
ADMIN_ONLY_TTS = {"gemini", "elevenlabs"}
ADMIN_ONLY_STT = {"smallest"}

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])

# Set during app startup
bot_config_loader: BotConfigLoader | None = None


def set_dependencies(loader: BotConfigLoader):
    global bot_config_loader
    bot_config_loader = loader


@router.post("", response_model=BotConfigResponse, status_code=201)
async def create_bot(
    req: CreateBotConfigRequest,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    user: User = Depends(get_current_user),
):
    # Enforce provider restrictions for non-super-admins
    if user.role != "super_admin":
        if req.tts_provider in ADMIN_ONLY_TTS:
            req.tts_provider = "sarvam"
        if req.stt_provider in ADMIN_ONLY_STT:
            req.stt_provider = "deepgram"

    # Cross-validate callback_schedule
    if req.callback_schedule:
        for i, step in enumerate(req.callback_schedule.steps):
            if step.preferred_window:
                pw_start, pw_end = step.preferred_window
                if pw_end <= req.callback_window_start or pw_start >= req.callback_window_end:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {i+1} preferred window [{pw_start}-{pw_end}] "
                               f"is entirely outside calling window [{req.callback_window_start}-{req.callback_window_end}]"
                    )

    bot = BotConfig(
        org_id=org_id,
        agent_name=req.agent_name,
        company_name=req.company_name,
        location=req.location,
        event_name=req.event_name,
        event_date=req.event_date,
        event_time=req.event_time,
        stt_provider=req.stt_provider,
        tts_voice=req.tts_voice,
        tts_style_prompt=req.tts_style_prompt,
        language=req.language,
        system_prompt_template=req.system_prompt_template,
        context_variables=req.context_variables,
        silence_timeout_secs=req.silence_timeout_secs,
        ghl_webhook_url=req.ghl_webhook_url,
        plivo_auth_id=req.plivo_auth_id,
        plivo_auth_token=req.plivo_auth_token,
        plivo_caller_id=req.plivo_caller_id,
        phone_number_id=req.phone_number_id,
        goal_config=req.goal_config.model_dump() if req.goal_config else None,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    if bot_config_loader:
        await bot_config_loader.publish_invalidation(str(bot.id))
    logger.info("bot_config_created", bot_id=str(bot.id))
    return bot


@router.get("", response_model=list[BotConfigResponse])
async def list_bots(
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    result = await db.execute(
        select(BotConfig)
        .where(BotConfig.is_active == True, BotConfig.org_id == org_id)
        .order_by(BotConfig.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot config not found")
    return bot


@router.patch("/{bot_id}", response_model=BotConfigResponse)
async def update_bot(
    bot_id: uuid.UUID,
    req: UpdateBotConfigRequest,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot config not found")

    update_data = req.model_dump(exclude_unset=True)

    # Enforce provider restrictions for non-super-admins
    if user.role != "super_admin":
        if update_data.get("tts_provider") in ADMIN_ONLY_TTS:
            update_data["tts_provider"] = "sarvam"
        if update_data.get("stt_provider") in ADMIN_ONLY_STT:
            update_data["stt_provider"] = "deepgram"

    # Cross-validate callback_schedule preferred_windows against calling window
    if "callback_schedule" in update_data and update_data["callback_schedule"]:
        from app.models.schemas import CallbackSchedule
        schedule_data = update_data["callback_schedule"]
        if isinstance(schedule_data, dict):
            schedule = CallbackSchedule(**schedule_data)
        else:
            schedule = schedule_data

        w_start = update_data.get("callback_window_start", bot.callback_window_start)
        w_end = update_data.get("callback_window_end", bot.callback_window_end)

        for i, step in enumerate(schedule.steps):
            if step.preferred_window:
                pw_start, pw_end = step.preferred_window
                if pw_end <= w_start or pw_start >= w_end:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {i+1} preferred window [{pw_start}-{pw_end}] "
                               f"is entirely outside calling window [{w_start}-{w_end}]"
                    )

        update_data["callback_schedule"] = schedule.model_dump()

    # Validate goal_config if provided as raw dict (PATCH may send raw JSON)
    if "goal_config" in update_data and update_data["goal_config"] is not None:
        try:
            validated = GoalConfig(**update_data["goal_config"])
            update_data["goal_config"] = validated.model_dump()
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid goal_config: {e}")

    for field, value in update_data.items():
        setattr(bot, field, value)
    bot.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(bot)

    # Invalidate cache
    if bot_config_loader:
        bot_config_loader.invalidate(str(bot_id))
        await bot_config_loader.publish_invalidation(str(bot_id))

    logger.info("bot_config_updated", bot_id=str(bot_id), fields=list(update_data.keys()))
    return bot


@router.post("/{bot_id}/clone", response_model=BotConfigResponse, status_code=201)
async def clone_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Clone an existing bot config with a new ID and '(Copy)' suffix on the name."""
    result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Bot config not found")

    clone = BotConfig(
        org_id=org_id,
        agent_name=original.agent_name + " (Copy)",
        company_name=original.company_name,
        location=original.location,
        event_name=original.event_name,
        event_date=original.event_date,
        event_time=original.event_time,
        stt_provider=original.stt_provider,
        tts_provider=original.tts_provider,
        tts_voice=original.tts_voice,
        tts_style_prompt=original.tts_style_prompt,
        language=original.language,
        system_prompt_template=original.system_prompt_template,
        context_variables=original.context_variables,
        silence_timeout_secs=original.silence_timeout_secs,
        ghl_webhook_url=original.ghl_webhook_url,
        ghl_api_key=original.ghl_api_key,
        ghl_location_id=original.ghl_location_id,
        ghl_post_call_tag=original.ghl_post_call_tag,
        ghl_workflows=original.ghl_workflows,
        max_call_duration=original.max_call_duration,
        telephony_provider=original.telephony_provider,
        phone_number_id=original.phone_number_id,
        goal_config=original.goal_config,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    if bot_config_loader:
        await bot_config_loader.publish_invalidation(str(clone.id))
    logger.info("bot_config_cloned", original_id=str(bot_id), clone_id=str(clone.id))
    return clone


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID = Depends(get_current_org),
):
    """Soft-delete: set is_active = false."""
    result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id, BotConfig.org_id == org_id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot config not found")

    bot.is_active = False
    bot.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if bot_config_loader:
        bot_config_loader.invalidate(str(bot_id))
        await bot_config_loader.publish_invalidation(str(bot_id))

    logger.info("bot_config_deleted", bot_id=str(bot_id))
