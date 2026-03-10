"""FastAPI dependencies for JWT authentication and role-based access control."""

from __future__ import annotations

import uuid
from typing import Callable

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.database import get_db
from app.models.user import User

logger = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Role hierarchy — higher index = more privilege
ROLE_HIERARCHY = {
    "client_user": 0,
    "client_admin": 1,
    "super_admin": 2,
}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode JWT and return the authenticated User.

    Raises 401 if token is invalid/expired or user not found.
    Raises 403 if user status is not active.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        if user_id is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active",
        )

    return user


def require_role(*roles: str) -> Callable:
    """Dependency factory that checks the current user has one of the allowed roles.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("client_admin", "super_admin"))])
        async def admin_endpoint(...):
            ...

    Or as a parameter dependency:
        async def endpoint(user: User = Depends(require_role("client_admin", "super_admin"))):
            ...
    """
    async def _role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not authorized. Required: {', '.join(roles)}",
            )
        return user

    return _role_checker


async def get_current_org(user: User = Depends(get_current_user)) -> uuid.UUID:
    """Return the org_id of the current authenticated user for scoping queries."""
    return user.org_id
