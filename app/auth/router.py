"""Auth API endpoints — signup, login, refresh, me, invite management."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.organization import Organization
from app.models.user import Invite, User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1)
    org_name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "client_user"


class AcceptInviteRequest(BaseModel):
    invite_id: uuid.UUID
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    org_id: uuid.UUID
    org_name: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InviteResponse(BaseModel):
    id: uuid.UUID
    email: str
    org_id: uuid.UUID
    org_name: str
    role: str
    status: str
    created_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert an org name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "org"


def _build_auth_response(
    user: User, org_name: str, access_token: str, refresh_token: str
) -> AuthResponse:
    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            org_id=user.org_id,
            org_name=org_name,
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Create a new organization and admin user."""
    # Check for existing user
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Create organization
    slug = _slugify(req.org_name)
    # Ensure slug uniqueness by appending a short suffix if needed
    slug_check = await db.execute(select(Organization).where(Organization.slug == slug))
    if slug_check.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    org = Organization(name=req.org_name, slug=slug)
    db.add(org)
    await db.flush()  # get org.id

    # Create admin user
    user = User(
        email=req.email,
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role="client_admin",
        org_id=org.id,
    )
    db.add(user)
    await db.flush()  # get user.id

    # Set org.created_by
    org.created_by = user.id
    await db.commit()
    await db.refresh(user)
    await db.refresh(org)

    # Generate tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("user_signup", user_id=str(user.id), org_id=str(org.id))

    return _build_auth_response(user, org.name, access_token, refresh_token)


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active",
        )

    # Update last_login_at
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    # Fetch org name
    org_result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = org_result.scalar_one()

    # Generate tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("user_login", user_id=str(user.id))

    return _build_auth_response(user, org.name, access_token, refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    access_token = create_access_token({"sub": user_id})
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current authenticated user info."""
    org_result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = org_result.scalar_one()

    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        org_id=user.org_id,
        org_name=org.name,
    )


@router.post("/invite", response_model=InviteResponse, status_code=201)
async def create_invite(
    req: InviteRequest,
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Invite a team member to the current organization."""
    # Validate role
    valid_roles = {"client_user", "client_admin"}
    if req.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}",
        )

    # Check if user already exists with this email
    existing_user = await db.execute(select(User).where(User.email == req.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Check for existing pending invite in this org
    existing_invite = await db.execute(
        select(Invite).where(
            Invite.email == req.email,
            Invite.org_id == user.org_id,
            Invite.status == "pending",
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invite for this email already exists",
        )

    # Fetch org name
    org_result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = org_result.scalar_one()

    invite = Invite(
        email=req.email,
        org_id=user.org_id,
        org_name=org.name,
        role=req.role,
        invited_by=user.id,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    logger.info("invite_created", invite_id=str(invite.id), email=req.email, org_id=str(user.org_id))

    return InviteResponse(
        id=invite.id,
        email=invite.email,
        org_id=invite.org_id,
        org_name=invite.org_name,
        role=invite.role,
        status=invite.status,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


@router.post("/accept-invite", response_model=AuthResponse, status_code=201)
async def accept_invite(req: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """Accept an invite and create a user account."""
    # Find the invite
    result = await db.execute(select(Invite).where(Invite.id == req.invite_id))
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        )

    if invite.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invite is no longer pending (status: {invite.status})",
        )

    # Check if invite has expired
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = "expired"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite has expired",
        )

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == invite.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Create user
    user = User(
        email=invite.email,
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role=invite.role,
        org_id=invite.org_id,
        invited_by=invite.invited_by,
    )
    db.add(user)

    # Mark invite as accepted
    invite.status = "accepted"

    await db.commit()
    await db.refresh(user)

    # Generate tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info(
        "invite_accepted",
        invite_id=str(invite.id),
        user_id=str(user.id),
        org_id=str(invite.org_id),
    )

    return _build_auth_response(user, invite.org_name, access_token, refresh_token)


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    user: User = Depends(require_role("client_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """List pending invites for the current organization."""
    result = await db.execute(
        select(Invite)
        .where(Invite.org_id == user.org_id, Invite.status == "pending")
        .order_by(Invite.created_at.desc())
    )
    invites = result.scalars().all()

    return [
        InviteResponse(
            id=inv.id,
            email=inv.email,
            org_id=inv.org_id,
            org_name=inv.org_name,
            role=inv.role,
            status=inv.status,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
        )
        for inv in invites
    ]
