"""Admin endpoints for linear -> flow migration."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.sequence import SequenceInstance, SequenceTemplate
from app.models.flow import FlowDefinition
from app.services.flow_migrator import migrate_template, migrate_all_templates

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/migration", tags=["migration"])


class MigrationStatusResponse(BaseModel):
    total_templates: int
    migrated: int
    remaining: int
    active_linear_instances: int
    templates: list[dict[str, Any]]


class MigrationPreviewResponse(BaseModel):
    template_id: str
    template_name: str
    node_count: int
    edge_count: int
    nodes: list[dict[str, str]]
    dry_run: bool = True


class MigrationResultResponse(BaseModel):
    template_id: str
    template_name: str
    flow_id: str | None = None
    version_id: str | None = None
    status: str | None = None
    node_count: int
    edge_count: int
    error: str | None = None


class BulkMigrationResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[dict[str, Any]]


@router.get("/status", response_model=MigrationStatusResponse)
async def migration_status(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationStatusResponse:
    """Get migration status for the current org."""
    # Count total active templates
    total_result = await db.execute(
        select(func.count()).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    total_templates = total_result.scalar_one()

    # Count templates that have a corresponding migrated flow
    migrated_result = await db.execute(
        select(func.count()).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name.like("% (migrated)"),
        )
    )
    migrated = migrated_result.scalar_one()

    # Count active linear instances
    active_result = await db.execute(
        select(func.count()).where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.status == "active",
            SequenceInstance.engine_type == "linear",
        )
    )
    active_linear = active_result.scalar_one()

    # List templates with migration status
    templates_result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    templates = templates_result.scalars().all()

    template_list = []
    for t in templates:
        flow_result = await db.execute(
            select(FlowDefinition.id).where(
                FlowDefinition.org_id == org_id,
                FlowDefinition.name == f"{t.name} (migrated)",
            )
        )
        flow_id = flow_result.scalar_one_or_none()
        template_list.append({
            "id": str(t.id),
            "name": t.name,
            "migrated": flow_id is not None,
            "flow_id": str(flow_id) if flow_id else None,
        })

    return MigrationStatusResponse(
        total_templates=total_templates,
        migrated=migrated,
        remaining=total_templates - migrated,
        active_linear_instances=active_linear,
        templates=template_list,
    )


@router.post("/preview/{template_id}", response_model=MigrationPreviewResponse)
async def preview_migration(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationPreviewResponse:
    """Preview what the migrated flow would look like (dry run)."""
    try:
        result = await migrate_template(db, template_id, org_id, dry_run=True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return MigrationPreviewResponse(**result)


@router.post("/convert/{template_id}", response_model=MigrationResultResponse)
async def convert_template(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationResultResponse:
    """Convert a single template to a flow (creates as draft)."""
    try:
        result = await migrate_template(db, template_id, org_id, dry_run=False)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await db.commit()
    return MigrationResultResponse(**result)


@router.post("/convert-all", response_model=BulkMigrationResponse)
async def convert_all_templates(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> BulkMigrationResponse:
    """Convert all active templates to flows (creates as drafts)."""
    results = await migrate_all_templates(db, org_id, dry_run=False)
    await db.commit()

    succeeded = sum(1 for r in results if "error" not in r)
    failed = sum(1 for r in results if "error" in r)

    return BulkMigrationResponse(
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.get("/linear-instances")
async def list_active_linear_instances(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List all active linear instances (for tracking completion before sunset)."""
    base = select(SequenceInstance).where(
        SequenceInstance.org_id == org_id,
        SequenceInstance.status == "active",
        SequenceInstance.engine_type == "linear",
    )

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.order_by(SequenceInstance.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": str(i.id),
                "template_id": str(i.template_id),
                "lead_id": str(i.lead_id),
                "status": i.status,
                "started_at": i.started_at.isoformat() if i.started_at else None,
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/cancel-all-linear")
async def cancel_all_linear_instances(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel all remaining active linear instances (use with caution)."""
    from sqlalchemy import update

    result = await db.execute(
        update(SequenceInstance)
        .where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.status == "active",
            SequenceInstance.engine_type == "linear",
        )
        .values(status="cancelled")
        .returning(SequenceInstance.id)
    )
    cancelled_ids = result.scalars().all()
    await db.commit()

    logger.info(
        "linear_instances_bulk_cancelled",
        org_id=str(org_id),
        count=len(cancelled_ids),
    )

    return {"cancelled": len(cancelled_ids)}
