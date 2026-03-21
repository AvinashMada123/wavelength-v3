"""REST API for sequence templates, steps, instances, touchpoints, and prompt testing."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.sequence import (
    SequenceInstance,
    SequenceStep,
    SequenceTemplate,
    SequenceTouchpoint,
)
from app.models.bot_config import BotConfig
from app.models.user import User
from app.services import anthropic_client
from app.services.sequence_engine import process_touchpoint

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/sequences", tags=["sequences"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TemplateVariable(BaseModel):
    key: str
    default_value: str = ""
    description: str = ""


class TemplateCreate(BaseModel):
    name: str
    bot_id: uuid.UUID | None = None
    trigger_type: str = "manual"
    trigger_conditions: dict[str, Any] = Field(default_factory=dict)
    max_active_per_lead: int = 1
    variables: list[TemplateVariable] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: str | None = None
    bot_id: uuid.UUID | None = None
    trigger_type: str | None = None
    trigger_conditions: dict[str, Any] | None = None
    max_active_per_lead: int | None = None
    variables: list[TemplateVariable] | None = None
    is_active: bool | None = None


class StepResponse(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    step_order: int
    name: str
    is_active: bool
    channel: str
    timing_type: str
    timing_value: dict[str, Any]
    skip_conditions: dict[str, Any] | None
    content_type: str
    whatsapp_template_name: str | None
    whatsapp_template_params: dict[str, Any] | None
    ai_prompt: str | None
    ai_model: str | None
    voice_bot_id: uuid.UUID | None
    expects_reply: bool
    reply_handler: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TemplateResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bot_id: uuid.UUID | None
    name: str
    trigger_type: str
    trigger_conditions: dict[str, Any]
    max_active_per_lead: int
    variables: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime
    steps: list[StepResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TemplateListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bot_id: uuid.UUID | None
    name: str
    trigger_type: str
    trigger_conditions: dict[str, Any]
    max_active_per_lead: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedTemplates(BaseModel):
    items: list[TemplateListItem]
    total: int
    page: int
    page_size: int


class StepCreate(BaseModel):
    step_order: int
    name: str
    channel: str
    timing_type: str
    timing_value: dict[str, Any]
    skip_conditions: dict[str, Any] | None = None
    content_type: str
    whatsapp_template_name: str | None = None
    whatsapp_template_params: dict[str, Any] | None = None
    ai_prompt: str | None = None
    ai_model: str | None = None
    voice_bot_id: uuid.UUID | None = None
    expects_reply: bool = False
    reply_handler: dict[str, Any] | None = None


class StepUpdate(BaseModel):
    name: str | None = None
    channel: str | None = None
    timing_type: str | None = None
    timing_value: dict[str, Any] | None = None
    skip_conditions: dict[str, Any] | None = None
    content_type: str | None = None
    whatsapp_template_name: str | None = None
    whatsapp_template_params: dict[str, Any] | None = None
    ai_prompt: str | None = None
    ai_model: str | None = None
    voice_bot_id: uuid.UUID | None = None
    expects_reply: bool | None = None
    reply_handler: dict[str, Any] | None = None
    is_active: bool | None = None


class ReorderRequest(BaseModel):
    step_ids: list[uuid.UUID]


class PromptTestRequest(BaseModel):
    prompt: str
    sample_variables: dict[str, Any] = Field(default_factory=dict)
    model: str = "claude-sonnet"


class PromptTestResponse(BaseModel):
    generated_content: str
    tokens_used: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_estimate: float
    model: str
    filled_prompt: str


class TouchpointResponse(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    step_id: uuid.UUID | None
    org_id: uuid.UUID
    lead_id: uuid.UUID | None
    step_order: int
    step_snapshot: dict[str, Any]
    status: str
    scheduled_at: datetime
    generated_content: str | None
    sent_at: datetime | None
    session_window_expires_at: datetime | None
    error_message: str | None
    reply_text: str | None
    reply_response: str | None
    retry_count: int
    max_retries: int
    messaging_provider_id: uuid.UUID | None
    queued_call_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InstanceResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    template_id: uuid.UUID
    lead_id: uuid.UUID
    trigger_call_id: uuid.UUID | None
    status: str
    context_data: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    touchpoints: list[TouchpointResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class InstanceListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    template_id: uuid.UUID
    lead_id: uuid.UUID
    trigger_call_id: uuid.UUID | None
    status: str
    context_data: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedInstances(BaseModel):
    items: list[InstanceListItem]
    total: int
    page: int
    page_size: int


class ImportStepData(BaseModel):
    step_order: int
    name: str
    channel: str
    timing_type: str
    timing_value: dict[str, Any]
    skip_conditions: dict[str, Any] | None = None
    content_type: str
    whatsapp_template_name: str | None = None
    whatsapp_template_params: dict[str, Any] | None = None
    ai_prompt: str | None = None
    ai_model: str | None = None
    expects_reply: bool = False
    reply_handler: dict[str, Any] | None = None


class ImportRequest(BaseModel):
    name: str
    trigger_type: str = "manual"
    trigger_conditions: dict[str, Any] = Field(default_factory=dict)
    max_active_per_lead: int = 1
    variables: list[TemplateVariable] = Field(default_factory=list)
    steps: list[ImportStepData] = Field(default_factory=list)


class ImportPreviewResponse(BaseModel):
    valid: bool
    name: str
    trigger_type: str
    step_count: int
    channels_used: list[str]
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rate limiting for prompt testing (in-memory, per org)
# ---------------------------------------------------------------------------

_prompt_test_usage: dict[str, list[float]] = {}

_PROMPT_TEST_LIMIT = 20
_PROMPT_TEST_WINDOW_SECS = 3600


def _check_prompt_rate_limit(org_id: str) -> None:
    """Raise 429 if org has exceeded 20 prompt tests in the last hour."""
    now = time.time()
    cutoff = now - _PROMPT_TEST_WINDOW_SECS
    timestamps = _prompt_test_usage.get(org_id, [])
    # Prune old entries
    timestamps = [t for t in timestamps if t > cutoff]
    _prompt_test_usage[org_id] = timestamps
    if len(timestamps) >= _PROMPT_TEST_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Prompt test rate limit exceeded ({_PROMPT_TEST_LIMIT}/hour). Try again later.",
        )


def _record_prompt_usage(org_id: str) -> None:
    _prompt_test_usage.setdefault(org_id, []).append(time.time())


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=PaginatedTemplates)
async def list_templates(
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List sequence templates for the current organisation."""
    base = select(SequenceTemplate).where(SequenceTemplate.org_id == org_id)

    # Default to showing only active templates (soft-deleted ones hidden)
    if is_active is None:
        base = base.where(SequenceTemplate.is_active == True)
    elif is_active is not None:
        base = base.where(SequenceTemplate.is_active == is_active)

    if search:
        base = base.where(SequenceTemplate.name.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = base.order_by(SequenceTemplate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedTemplates(items=items, total=total, page=page, page_size=page_size)


@router.post("/templates", response_model=TemplateListItem, status_code=201)
async def create_template(
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new sequence template."""
    # Duplicate name check
    dup = await db.execute(
        select(SequenceTemplate.id).where(
            SequenceTemplate.org_id == org_id, SequenceTemplate.name == body.name
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Template named '{body.name}' already exists")

    template = SequenceTemplate(
        org_id=org_id,
        name=body.name,
        bot_id=body.bot_id,
        trigger_type=body.trigger_type,
        trigger_conditions=body.trigger_conditions,
        max_active_per_lead=body.max_active_per_lead,
        variables=[v.model_dump() for v in body.variables] if body.variables else [],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    logger.info("template_created", template_id=str(template.id), org_id=str(org_id))
    return template


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get a template with all its steps."""
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    steps_result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.template_id == template_id)
        .order_by(SequenceStep.step_order)
    )
    steps = steps_result.scalars().all()

    return TemplateResponse(
        id=template.id,
        org_id=template.org_id,
        bot_id=template.bot_id,
        name=template.name,
        trigger_type=template.trigger_type,
        trigger_conditions=template.trigger_conditions,
        max_active_per_lead=template.max_active_per_lead,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
        steps=steps,
    )


@router.put("/templates/{template_id}", response_model=TemplateListItem)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update a sequence template."""
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = body.model_dump(exclude_unset=True)

    # If renaming, check for duplicate
    if "name" in update_data and update_data["name"] != template.name:
        dup = await db.execute(
            select(SequenceTemplate.id).where(
                SequenceTemplate.org_id == org_id,
                SequenceTemplate.name == update_data["name"],
                SequenceTemplate.id != template_id,
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Template named '{update_data['name']}' already exists")

    for field, value in update_data.items():
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)

    logger.info("template_updated", template_id=str(template_id), fields=list(update_data.keys()))
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a template (set is_active=false)."""
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    template.is_active = False
    await db.commit()

    logger.info("template_soft_deleted", template_id=str(template_id), org_id=str(org_id))


# ---------------------------------------------------------------------------
# Step management
# ---------------------------------------------------------------------------


@router.post("/templates/{template_id}/steps", response_model=StepResponse, status_code=201)
async def add_step(
    template_id: uuid.UUID,
    body: StepCreate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Add a step to a template."""
    # Verify template belongs to org
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate voice_bot_id exists and belongs to same org
    if body.voice_bot_id:
        bot_result = await db.execute(
            select(BotConfig).where(BotConfig.id == body.voice_bot_id, BotConfig.org_id == org_id)
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Voice bot not found or does not belong to this organization")

    step = SequenceStep(
        template_id=template_id,
        step_order=body.step_order,
        name=body.name,
        channel=body.channel,
        timing_type=body.timing_type,
        timing_value=body.timing_value,
        skip_conditions=body.skip_conditions,
        content_type=body.content_type,
        whatsapp_template_name=body.whatsapp_template_name,
        whatsapp_template_params=body.whatsapp_template_params,
        ai_prompt=body.ai_prompt,
        ai_model=body.ai_model,
        voice_bot_id=body.voice_bot_id,
        expects_reply=body.expects_reply,
        reply_handler=body.reply_handler,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)

    logger.info("step_created", step_id=str(step.id), template_id=str(template_id))
    return step


@router.put("/steps/{step_id}", response_model=StepResponse)
async def update_step(
    step_id: uuid.UUID,
    body: StepUpdate,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Update a sequence step."""
    result = await db.execute(
        select(SequenceStep)
        .join(SequenceTemplate, SequenceStep.template_id == SequenceTemplate.id)
        .where(SequenceStep.id == step_id, SequenceTemplate.org_id == org_id)
    )
    step = result.scalar_one_or_none()
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    update_data = body.model_dump(exclude_unset=True)

    # Validate voice_bot_id if being updated
    if "voice_bot_id" in update_data and update_data["voice_bot_id"]:
        bot_result = await db.execute(
            select(BotConfig).where(BotConfig.id == update_data["voice_bot_id"], BotConfig.org_id == org_id)
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Voice bot not found or does not belong to this organization")

    for field, value in update_data.items():
        setattr(step, field, value)

    await db.commit()
    await db.refresh(step)

    logger.info("step_updated", step_id=str(step_id), fields=list(update_data.keys()))
    return step


@router.delete("/steps/{step_id}", status_code=204)
async def delete_step(
    step_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Remove a step from a template."""
    result = await db.execute(
        select(SequenceStep)
        .join(SequenceTemplate, SequenceStep.template_id == SequenceTemplate.id)
        .where(SequenceStep.id == step_id, SequenceTemplate.org_id == org_id)
    )
    step = result.scalar_one_or_none()
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    await db.delete(step)
    await db.commit()

    logger.info("step_deleted", step_id=str(step_id))


@router.post("/templates/{template_id}/reorder", status_code=200)
async def reorder_steps(
    template_id: uuid.UUID,
    body: ReorderRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Reorder steps within a template. Accepts ordered list of step IDs."""
    # Verify template belongs to org
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Load all steps for this template
    steps_result = await db.execute(
        select(SequenceStep).where(SequenceStep.template_id == template_id)
    )
    steps_by_id = {s.id: s for s in steps_result.scalars().all()}

    # Validate all IDs belong to this template
    for sid in body.step_ids:
        if sid not in steps_by_id:
            raise HTTPException(status_code=400, detail=f"Step {sid} not found in template")

    # First set all to negative to avoid unique constraint conflicts
    for i, sid in enumerate(body.step_ids):
        steps_by_id[sid].step_order = -(i + 1)
    await db.flush()

    # Now set to correct positive values
    for i, sid in enumerate(body.step_ids):
        steps_by_id[sid].step_order = i + 1

    await db.commit()

    logger.info("steps_reordered", template_id=str(template_id), count=len(body.step_ids))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Step testing
# ---------------------------------------------------------------------------


class TestStepRequest(BaseModel):
    phone: str
    variables: dict[str, Any] = Field(default_factory=dict)


@router.post("/steps/{step_id}/test")
async def test_step(
    step_id: uuid.UUID,
    body: TestStepRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Send a single step to a test phone number for verification."""
    # Load step + template
    result = await db.execute(
        select(SequenceStep)
        .join(SequenceTemplate, SequenceStep.template_id == SequenceTemplate.id)
        .where(SequenceStep.id == step_id, SequenceTemplate.org_id == org_id)
    )
    step = result.scalar_one_or_none()
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    # Load template for variables
    tmpl_result = await db.execute(
        select(SequenceTemplate).where(SequenceTemplate.id == step.template_id)
    )
    template = tmpl_result.scalar_one_or_none()

    # Build variables: template defaults merged with test overrides
    variables = {}
    if template and template.variables:
        for v in template.variables:
            if isinstance(v, dict):
                variables[v.get("key", "")] = v.get("default_value", "")
    variables.update(body.variables)
    variables["contact_phone"] = body.phone

    # Determine channel
    channel = step.channel
    if channel not in ("whatsapp_template", "whatsapp_session", "sms"):
        if channel == "voice_call":
            return {"success": False, "error": "Voice call testing not supported yet — trigger a call instead."}
        return {"success": False, "error": f"Unsupported channel for testing: {channel}"}

    # Get default messaging provider for org
    from app.models.messaging_provider import MessagingProvider
    prov_result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.org_id == org_id,
            MessagingProvider.is_default == True,
        ).limit(1)
    )
    provider = prov_result.scalar_one_or_none()
    if not provider:
        return {"success": False, "error": "No default messaging provider configured. Go to Settings → Messaging Providers."}

    # Resolve template params with variables
    from app.services.messaging_client import send_template, send_session_message

    phone = body.phone.strip().lstrip("+")

    if channel == "whatsapp_template":
        template_name = step.whatsapp_template_name
        if not template_name:
            return {"success": False, "error": "No WhatsApp template name configured on this step."}

        # Resolve params: replace {{var}} with actual values
        raw_params = step.whatsapp_template_params or {}
        if isinstance(raw_params, dict):
            resolved = []
            for key in sorted(raw_params.keys()):
                val = raw_params[key]
                for var_key, var_val in variables.items():
                    val = val.replace("{{" + var_key + "}}", str(var_val))
                resolved.append({"name": key, "value": val})
        else:
            resolved = raw_params

        result = await send_template(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            template_name=template_name,
            params=resolved,
        )
        return {"success": result.success, "message_id": result.message_id, "error": result.error}

    elif channel == "whatsapp_session":
        # For session messages, use AI prompt or static text
        text = step.ai_prompt or "Test session message from Wavelength"
        for var_key, var_val in variables.items():
            text = text.replace("{{" + var_key + "}}", str(var_val))

        result = await send_session_message(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            text=text,
        )
        return {"success": result.success, "message_id": result.message_id, "error": result.error}

    return {"success": False, "error": "Unhandled channel"}


# ---------------------------------------------------------------------------
# Prompt testing
# ---------------------------------------------------------------------------


@router.post("/test-prompt", response_model=PromptTestResponse)
async def test_prompt(
    body: PromptTestRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Test an AI prompt with sample variables. Rate-limited to 20/hour per org."""
    org_key = str(org_id)
    _check_prompt_rate_limit(org_key)

    try:
        result = await anthropic_client.test_prompt(
            prompt=body.prompt,
            sample_variables=body.sample_variables,
            model=body.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Prompt test failed: {exc}")

    _record_prompt_usage(org_key)
    return PromptTestResponse(**result)


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------


@router.get("/templates/{template_id}/export")
async def export_template(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Export a template + steps as JSON."""
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id, SequenceTemplate.org_id == org_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    steps_result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.template_id == template_id)
        .order_by(SequenceStep.step_order)
    )
    steps = steps_result.scalars().all()

    return {
        "name": template.name,
        "trigger_type": template.trigger_type,
        "trigger_conditions": template.trigger_conditions,
        "max_active_per_lead": template.max_active_per_lead,
        "variables": template.variables or [],
        "steps": [
            {
                "step_order": s.step_order,
                "name": s.name,
                "channel": s.channel,
                "timing_type": s.timing_type,
                "timing_value": s.timing_value,
                "skip_conditions": s.skip_conditions,
                "content_type": s.content_type,
                "whatsapp_template_name": s.whatsapp_template_name,
                "whatsapp_template_params": s.whatsapp_template_params,
                "ai_prompt": s.ai_prompt,
                "ai_model": s.ai_model,
                "expects_reply": s.expects_reply,
                "reply_handler": s.reply_handler,
            }
            for s in steps
        ],
    }


@router.post("/templates/import", response_model=TemplateListItem, status_code=201)
async def import_template(
    body: ImportRequest,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Import a template from JSON (exported format)."""
    # Duplicate name check
    dup = await db.execute(
        select(SequenceTemplate.id).where(
            SequenceTemplate.org_id == org_id, SequenceTemplate.name == body.name
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Template named '{body.name}' already exists")

    template = SequenceTemplate(
        org_id=org_id,
        name=body.name,
        trigger_type=body.trigger_type,
        trigger_conditions=body.trigger_conditions,
        max_active_per_lead=body.max_active_per_lead,
        variables=[v.model_dump() for v in body.variables] if body.variables else [],
    )
    db.add(template)
    await db.flush()

    for step_data in body.steps:
        step = SequenceStep(
            template_id=template.id,
            step_order=step_data.step_order,
            name=step_data.name,
            channel=step_data.channel,
            timing_type=step_data.timing_type,
            timing_value=step_data.timing_value,
            skip_conditions=step_data.skip_conditions,
            content_type=step_data.content_type,
            whatsapp_template_name=step_data.whatsapp_template_name,
            whatsapp_template_params=step_data.whatsapp_template_params,
            ai_prompt=step_data.ai_prompt,
            ai_model=step_data.ai_model,
            expects_reply=step_data.expects_reply,
            reply_handler=step_data.reply_handler,
        )
        db.add(step)

    await db.commit()
    await db.refresh(template)

    logger.info("template_imported", template_id=str(template.id), org_id=str(org_id), steps=len(body.steps))
    return template


@router.post("/templates/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    body: ImportRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Validate import JSON and return a preview without creating anything."""
    errors: list[str] = []

    if not body.name:
        errors.append("Template name is required")

    # Check duplicate name
    dup = await db.execute(
        select(SequenceTemplate.id).where(
            SequenceTemplate.org_id == org_id, SequenceTemplate.name == body.name
        )
    )
    if dup.scalar_one_or_none() is not None:
        errors.append(f"Template named '{body.name}' already exists")

    valid_channels = {"whatsapp_template", "whatsapp_session", "voice_call", "sms"}
    channels_used: set[str] = set()

    for i, step in enumerate(body.steps):
        if step.channel not in valid_channels:
            errors.append(f"Step {i + 1}: invalid channel '{step.channel}'")
        channels_used.add(step.channel)

    return ImportPreviewResponse(
        valid=len(errors) == 0,
        name=body.name,
        trigger_type=body.trigger_type,
        step_count=len(body.steps),
        channels_used=sorted(channels_used),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Instance monitoring
# ---------------------------------------------------------------------------


@router.get("/instances", response_model=PaginatedInstances)
async def list_instances(
    lead_id: uuid.UUID | None = Query(None),
    template_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List sequence instances with optional filtering."""
    base = select(SequenceInstance).where(SequenceInstance.org_id == org_id)

    if lead_id:
        base = base.where(SequenceInstance.lead_id == lead_id)
    if template_id:
        base = base.where(SequenceInstance.template_id == template_id)
    if status:
        base = base.where(SequenceInstance.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = base.order_by(SequenceInstance.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return PaginatedInstances(items=items, total=total, page=page, page_size=page_size)


@router.get("/instances/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get an instance with all its touchpoints."""
    result = await db.execute(
        select(SequenceInstance).where(
            SequenceInstance.id == instance_id, SequenceInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    tp_result = await db.execute(
        select(SequenceTouchpoint)
        .where(SequenceTouchpoint.instance_id == instance_id)
        .order_by(SequenceTouchpoint.step_order)
    )
    touchpoints = tp_result.scalars().all()

    return InstanceResponse(
        id=instance.id,
        org_id=instance.org_id,
        template_id=instance.template_id,
        lead_id=instance.lead_id,
        trigger_call_id=instance.trigger_call_id,
        status=instance.status,
        context_data=instance.context_data,
        started_at=instance.started_at,
        completed_at=instance.completed_at,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        touchpoints=touchpoints,
    )


@router.post("/instances/{instance_id}/pause", status_code=200)
async def pause_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Pause an active sequence instance."""
    result = await db.execute(
        select(SequenceInstance).where(
            SequenceInstance.id == instance_id, SequenceInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot pause instance with status '{instance.status}'")

    instance.status = "paused"
    await db.commit()

    logger.info("instance_paused", instance_id=str(instance_id))
    return {"ok": True, "status": "paused"}


@router.post("/instances/{instance_id}/resume", status_code=200)
async def resume_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused sequence instance."""
    result = await db.execute(
        select(SequenceInstance).where(
            SequenceInstance.id == instance_id, SequenceInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume instance with status '{instance.status}'")

    instance.status = "active"
    await db.commit()

    logger.info("instance_resumed", instance_id=str(instance_id))
    return {"ok": True, "status": "active"}


@router.post("/instances/{instance_id}/cancel", status_code=200)
async def cancel_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a sequence instance."""
    result = await db.execute(
        select(SequenceInstance).where(
            SequenceInstance.id == instance_id, SequenceInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel instance with status '{instance.status}'")

    instance.status = "cancelled"
    await db.commit()

    logger.info("instance_cancelled", instance_id=str(instance_id))
    return {"ok": True, "status": "cancelled"}


@router.post("/instances/{instance_id}/advance", status_code=200)
async def advance_instance(
    instance_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Force-execute the next pending touchpoint immediately (for testing)."""
    result = await db.execute(
        select(SequenceInstance).where(
            SequenceInstance.id == instance_id, SequenceInstance.org_id == org_id
        )
    )
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status not in ("active", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot advance instance with status '{instance.status}'",
        )

    # Find next pending touchpoint by step_order
    tp_result = await db.execute(
        select(SequenceTouchpoint)
        .where(
            SequenceTouchpoint.instance_id == instance_id,
            SequenceTouchpoint.status == "pending",
        )
        .order_by(SequenceTouchpoint.step_order)
        .limit(1)
    )
    touchpoint = tp_result.scalar_one_or_none()
    if touchpoint is None:
        raise HTTPException(
            status_code=400,
            detail="No pending touchpoints to advance — sequence may be complete or awaiting reply",
        )

    # Ensure instance is active for processing
    if instance.status == "paused":
        instance.status = "active"
        await db.flush()

    # Force-execute the touchpoint now
    await process_touchpoint(db, touchpoint)

    logger.info(
        "instance_advanced",
        instance_id=str(instance_id),
        touchpoint_id=str(touchpoint.id),
        step_order=touchpoint.step_order,
    )
    return {
        "ok": True,
        "touchpoint_id": str(touchpoint.id),
        "step_order": touchpoint.step_order,
        "step_name": (touchpoint.step_snapshot or {}).get("name", ""),
        "status": touchpoint.status,
    }


# ---------------------------------------------------------------------------
# Touchpoints
# ---------------------------------------------------------------------------


@router.get("/touchpoints/{touchpoint_id}", response_model=TouchpointResponse)
async def get_touchpoint(
    touchpoint_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Get full detail of a single touchpoint."""
    result = await db.execute(
        select(SequenceTouchpoint).where(
            SequenceTouchpoint.id == touchpoint_id, SequenceTouchpoint.org_id == org_id
        )
    )
    touchpoint = result.scalar_one_or_none()
    if touchpoint is None:
        raise HTTPException(status_code=404, detail="Touchpoint not found")
    return touchpoint


@router.post("/touchpoints/{touchpoint_id}/retry", status_code=200)
async def retry_touchpoint(
    touchpoint_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Reset a touchpoint to pending for retry."""
    result = await db.execute(
        select(SequenceTouchpoint).where(
            SequenceTouchpoint.id == touchpoint_id, SequenceTouchpoint.org_id == org_id
        )
    )
    touchpoint = result.scalar_one_or_none()
    if touchpoint is None:
        raise HTTPException(status_code=404, detail="Touchpoint not found")

    touchpoint.status = "pending"
    touchpoint.retry_count = 0
    touchpoint.error_message = None
    await db.commit()

    logger.info("touchpoint_retried", touchpoint_id=str(touchpoint_id))
    return {"ok": True, "status": "pending"}
