"""Super Admin API endpoints — manage all organizations, users, and platform stats."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.auth.security import create_access_token, create_refresh_token, hash_password
from app.database import get_db
from app.models.bot_config import BotConfig
from app.models.call_log import CallLog
from app.models.organization import Organization
from app.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class OrgCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    plan: str | None = None
    status: str | None = None


class OrgUpdateRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    status: str | None = None
    settings: dict | None = None


class OrgSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str
    settings: dict
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    user_count: int
    bot_count: int
    call_count: int


class UserInOrg(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None


class BotInOrg(BaseModel):
    id: uuid.UUID
    agent_name: str
    company_name: str
    is_active: bool
    created_at: datetime


class OrgDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str
    settings: dict
    usage: dict
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    users: list[UserInOrg]
    bots: list[BotInOrg]


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str
    settings: dict
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    org_id: uuid.UUID
    org_name: str
    created_at: datetime
    last_login_at: datetime | None


class UserCreateRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=8)
    role: str = "client_user"
    org_id: uuid.UUID


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8)
    display_name: str | None = None
    role: str | None = None


class ImpersonateResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    email: str
    role: str
    org_id: uuid.UUID


class StatusBreakdown(BaseModel):
    status: str
    count: int


class PlatformStatsResponse(BaseModel):
    total_orgs: int
    total_users: int
    total_bots: int
    total_calls: int
    total_calls_today: int
    calls_by_status: list[StatusBreakdown]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert an org name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "org"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/organizations", response_model=list[OrgSummaryResponse])
async def list_organizations(
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all organizations with aggregate counts."""
    user_count_sq = (
        select(func.count(User.id))
        .where(User.org_id == Organization.id)
        .correlate(Organization)
        .scalar_subquery()
    )
    bot_count_sq = (
        select(func.count(BotConfig.id))
        .where(BotConfig.org_id == Organization.id)
        .correlate(Organization)
        .scalar_subquery()
    )
    call_count_sq = (
        select(func.count(CallLog.id))
        .where(CallLog.org_id == Organization.id)
        .correlate(Organization)
        .scalar_subquery()
    )

    stmt = (
        select(
            Organization,
            user_count_sq.label("user_count"),
            bot_count_sq.label("bot_count"),
            call_count_sq.label("call_count"),
        )
        .order_by(Organization.created_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        OrgSummaryResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            status=org.status,
            settings=org.settings,
            created_by=org.created_by,
            created_at=org.created_at,
            updated_at=org.updated_at,
            user_count=uc,
            bot_count=bc,
            call_count=cc,
        )
        for org, uc, bc, cc in rows
    ]


@router.get("/organizations/{org_id}", response_model=OrgDetailResponse)
async def get_organization(
    org_id: uuid.UUID,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get organization detail with users and bots."""
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Fetch users in org
    users_result = await db.execute(
        select(User).where(User.org_id == org_id).order_by(User.created_at.desc())
    )
    users = users_result.scalars().all()

    # Fetch bots in org
    bots_result = await db.execute(
        select(BotConfig).where(BotConfig.org_id == org_id).order_by(BotConfig.created_at.desc())
    )
    bots = bots_result.scalars().all()

    return OrgDetailResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        status=org.status,
        settings=org.settings,
        usage=org.usage,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
        users=[
            UserInOrg(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=u.role,
                status=u.status,
                created_at=u.created_at,
                last_login_at=u.last_login_at,
            )
            for u in users
        ],
        bots=[
            BotInOrg(
                id=b.id,
                agent_name=b.agent_name,
                company_name=b.company_name,
                is_active=b.is_active,
                created_at=b.created_at,
            )
            for b in bots
        ],
    )


@router.post("/organizations", response_model=OrgResponse, status_code=201)
async def create_organization(
    req: OrgCreateRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization."""
    slug = req.slug if req.slug else _slugify(req.name)

    # Ensure slug uniqueness
    slug_check = await db.execute(select(Organization).where(Organization.slug == slug))
    if slug_check.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    org = Organization(
        name=req.name,
        slug=slug,
        created_by=user.id,
    )
    if req.plan is not None:
        org.plan = req.plan
    if req.status is not None:
        org.status = req.status

    db.add(org)
    await db.commit()
    await db.refresh(org)

    logger.info("admin_org_created", org_id=str(org.id), slug=org.slug, by=str(user.id))

    return OrgResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        status=org.status,
        settings=org.settings,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.put("/organizations/{org_id}", response_model=OrgResponse)
async def update_organization(
    org_id: uuid.UUID,
    req: OrgUpdateRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update an organization (partial update)."""
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if req.name is not None:
        org.name = req.name
    if req.plan is not None:
        org.plan = req.plan
    if req.status is not None:
        org.status = req.status
    if req.settings is not None:
        org.settings = req.settings

    org.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(org)

    logger.info("admin_org_updated", org_id=str(org.id), by=str(user.id))

    return OrgResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        status=org.status,
        settings=org.settings,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    org_id: uuid.UUID | None = Query(None, description="Filter by organization"),
    role: str | None = Query(None, description="Filter by role"),
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users across all organizations with optional filters."""
    stmt = (
        select(User, Organization.name.label("org_name"))
        .join(Organization, User.org_id == Organization.id)
    )

    if org_id is not None:
        stmt = stmt.where(User.org_id == org_id)
    if role is not None:
        stmt = stmt.where(User.role == role)

    stmt = stmt.order_by(User.created_at.desc())

    result = await db.execute(stmt)
    rows = result.all()

    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            status=u.status,
            org_id=u.org_id,
            org_name=org_name,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
        )
        for u, org_name in rows
    ]


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_user(
    req: UserCreateRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a user in any organization (super admin only)."""
    # Validate org exists
    org_result = await db.execute(select(Organization).where(Organization.id == req.org_id))
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Check for existing user with same email
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Validate role
    valid_roles = {"client_user", "client_admin", "super_admin"}
    if req.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}",
        )

    new_user = User(
        email=req.email,
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role=req.role,
        org_id=req.org_id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "admin_user_created",
        user_id=str(new_user.id),
        email=new_user.email,
        org_id=str(req.org_id),
        by=str(user.id),
    )

    return AdminUserResponse(
        id=new_user.id,
        email=new_user.email,
        display_name=new_user.display_name,
        role=new_user.role,
        status=new_user.status,
        org_id=new_user.org_id,
        org_name=org.name,
        created_at=new_user.created_at,
        last_login_at=new_user.last_login_at,
    )


@router.put("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    req: UserUpdateRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's email, password, display name, or role (super admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if req.email is not None and req.email != target_user.email:
        existing = await db.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )
        target_user.email = req.email

    if req.password is not None:
        target_user.password_hash = hash_password(req.password)

    if req.display_name is not None:
        target_user.display_name = req.display_name

    if req.role is not None:
        valid_roles = {"client_user", "client_admin", "super_admin"}
        if req.role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}",
            )
        target_user.role = req.role

    await db.commit()
    await db.refresh(target_user)

    org_result = await db.execute(
        select(Organization.name).where(Organization.id == target_user.org_id)
    )
    org_name = org_result.scalar_one_or_none() or ""

    logger.info(
        "admin_user_updated",
        user_id=str(user_id),
        fields=[f for f in ("email", "password", "display_name", "role") if getattr(req, f if f != "password" else "password") is not None],
        by=str(user.id),
    )

    return AdminUserResponse(
        id=target_user.id,
        email=target_user.email,
        display_name=target_user.display_name,
        role=target_user.role,
        status=target_user.status,
        org_id=target_user.org_id,
        org_name=org_name,
        created_at=target_user.created_at,
        last_login_at=target_user.last_login_at,
    )


@router.delete("/users/{user_id}", status_code=200)
async def deactivate_user(
    user_id: uuid.UUID,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user (soft delete)."""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already inactive",
        )

    target_user.status = "inactive"
    await db.commit()

    logger.info("admin_user_deactivated", user_id=str(user_id), by=str(user.id))

    return {"detail": "User deactivated", "user_id": str(user_id)}


@router.post("/impersonate/{user_id}", response_model=ImpersonateResponse)
async def impersonate_user(
    user_id: uuid.UUID,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Generate tokens for a specific user (impersonation)."""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot impersonate an inactive user",
        )

    token_data = {"sub": str(target_user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info(
        "admin_impersonate",
        target_user_id=str(user_id),
        by=str(user.id),
    )

    return ImpersonateResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=target_user.id,
        email=target_user.email,
        role=target_user.role,
        org_id=target_user.org_id,
    )


class OrgSettingsUpdateRequest(BaseModel):
    max_concurrent_calls: int | None = Field(None, ge=1, le=100)


class OrgSettingsResponse(BaseModel):
    org_id: uuid.UUID
    org_name: str
    max_concurrent_calls: int


@router.get("/organizations/{org_id}/settings", response_model=OrgSettingsResponse)
async def get_org_settings(
    org_id: uuid.UUID,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get org-level platform settings."""
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = org.settings or {}
    return OrgSettingsResponse(
        org_id=org.id,
        org_name=org.name,
        max_concurrent_calls=int(settings.get("max_concurrent_calls", 15)),
    )


@router.patch("/organizations/{org_id}/settings", response_model=OrgSettingsResponse)
async def update_org_settings(
    org_id: uuid.UUID,
    req: OrgSettingsUpdateRequest,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update org-level platform settings (super admin only)."""
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = dict(org.settings or {})
    if req.max_concurrent_calls is not None:
        settings["max_concurrent_calls"] = req.max_concurrent_calls

    org.settings = settings
    org.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(org)

    logger.info(
        "admin_org_settings_updated",
        org_id=str(org_id),
        max_concurrent_calls=req.max_concurrent_calls,
        by=str(user.id),
    )

    return OrgSettingsResponse(
        org_id=org.id,
        org_name=org.name,
        max_concurrent_calls=int(settings.get("max_concurrent_calls", 15)),
    )


@router.get("/stats", response_model=PlatformStatsResponse)
async def platform_stats(
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide statistics."""
    # Total counts
    total_orgs = (await db.execute(select(func.count(Organization.id)))).scalar_one()
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_bots = (await db.execute(select(func.count(BotConfig.id)))).scalar_one()
    total_calls = (await db.execute(select(func.count(CallLog.id)))).scalar_one()

    # Calls today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total_calls_today = (
        await db.execute(
            select(func.count(CallLog.id)).where(CallLog.created_at >= today_start)
        )
    ).scalar_one()

    # Calls by status breakdown
    status_result = await db.execute(
        select(CallLog.status, func.count(CallLog.id).label("count"))
        .group_by(CallLog.status)
        .order_by(func.count(CallLog.id).desc())
    )
    calls_by_status = [
        StatusBreakdown(status=row.status, count=row.count)
        for row in status_result.all()
    ]

    return PlatformStatsResponse(
        total_orgs=total_orgs,
        total_users=total_users,
        total_bots=total_bots,
        total_calls=total_calls,
        total_calls_today=total_calls_today,
        calls_by_status=calls_by_status,
    )
