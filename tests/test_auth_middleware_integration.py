"""Integration tests for auth middleware using a real test database.

Tests that protected endpoints correctly block unauthenticated requests.
Covers: no token, expired token, malformed token, valid token.
Uses httpx.AsyncClient (Python equivalent of Supertest) against the real FastAPI app
with a real PostgreSQL test database.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.security import create_access_token, hash_password
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User

# ---------------------------------------------------------------------------
# Two separate engines to avoid asyncpg connection pool conflicts between
# fixture setup/teardown and the HTTP test client.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", settings.DATABASE_URL)

# NullPool avoids connection reuse across event loops (pytest-asyncio creates
# a new loop per test with asyncio_default_test_loop_scope=function).
app_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
AppSessionFactory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

fixture_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
FixtureSessionFactory = async_sessionmaker(fixture_engine, class_=AsyncSession, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Lightweight FastAPI app for testing (avoids heavy lifespan startup)
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from app.auth import router as auth_router


def create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the auth router mounted."""
    test_app = FastAPI()
    test_app.include_router(auth_router.router)

    async def _override_get_db():
        async with AppSessionFactory() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


_test_app = create_test_app()


# ---------------------------------------------------------------------------
# Data classes for fixture return values
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeedData:
    org_id: uuid.UUID
    org_name: str
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str


@dataclass(frozen=True)
class InactiveData:
    user_id: uuid.UUID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    """Provide an httpx AsyncClient wired to the test app."""
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seed_user():
    """Create an org + active user in the real DB. Cleaned up after the test."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"test-{user_id.hex[:8]}@example.com"

    async with FixtureSessionFactory() as session:
        org = Organization(
            id=org_id,
            name="Test Org",
            slug=f"test-org-{org_id.hex[:8]}",
            plan="free",
            status="active",
        )
        session.add(org)
        await session.flush()

        user = User(
            id=user_id,
            email=email,
            display_name="Test User",
            password_hash=hash_password("testpassword123"),
            role="client_admin",
            org_id=org_id,
            status="active",
        )
        session.add(user)
        await session.commit()

    yield SeedData(
        org_id=org_id,
        org_name="Test Org",
        user_id=user_id,
        email=email,
        display_name="Test User",
        role="client_admin",
    )

    # Cleanup
    async with FixtureSessionFactory() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


@pytest_asyncio.fixture
async def inactive_user(seed_user):
    """Create an inactive user in the same org as seed_user."""
    user_id = uuid.uuid4()

    async with FixtureSessionFactory() as session:
        user = User(
            id=user_id,
            email=f"inactive-{user_id.hex[:8]}@example.com",
            display_name="Inactive User",
            password_hash=hash_password("testpassword123"),
            role="client_admin",
            org_id=seed_user.org_id,
            status="suspended",
        )
        session.add(user)
        await session.commit()

    yield InactiveData(user_id=user_id)

    async with FixtureSessionFactory() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


# ---------------------------------------------------------------------------
# Engine disposal after all tests in this module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def dispose_engines(request):
    """Dispose both engines after the test module completes."""
    import asyncio

    def _dispose():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(app_engine.dispose())
        loop.run_until_complete(fixture_engine.dispose())
        loop.close()

    request.addfinalizer(_dispose)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROTECTED_ENDPOINT = "/api/auth/me"


def make_expired_token(user_id: uuid.UUID) -> str:
    """Create a JWT that expired 1 hour ago."""
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def make_valid_token(user_id: uuid.UUID) -> str:
    """Create a valid access token for the given user."""
    return create_access_token({"sub": str(user_id)})


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Tests
# ===========================================================================


class TestNoToken:
    """Requests without any Authorization header should be rejected."""

    @pytest.mark.asyncio
    async def test_no_auth_header_returns_401(self, client: AsyncClient):
        resp = await client.get(PROTECTED_ENDPOINT)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_header_error_detail(self, client: AsyncClient):
        resp = await client.get(PROTECTED_ENDPOINT)
        assert resp.json()["detail"] == "Not authenticated"

    @pytest.mark.asyncio
    async def test_empty_bearer_returns_401(self, client: AsyncClient):
        resp = await client.get(PROTECTED_ENDPOINT, headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


class TestExpiredToken:
    """Requests with an expired JWT should be rejected with 401."""

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, client: AsyncClient, seed_user):
        token = make_expired_token(seed_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_error_message(self, client: AsyncClient, seed_user):
        token = make_expired_token(seed_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.json()["detail"] == "Invalid or expired token"


class TestMalformedToken:
    """Requests with malformed/invalid JWTs should be rejected."""

    @pytest.mark.asyncio
    async def test_random_string_returns_401(self, client: AsyncClient):
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header("not-a-jwt"))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self, client: AsyncClient, seed_user):
        """Token signed with a different secret should be rejected."""
        payload = {
            "sub": str(seed_user.user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_rejected_on_access_endpoint(self, client: AsyncClient, seed_user):
        """A refresh token (type != 'access') should not work on protected endpoints."""
        payload = {
            "sub": str(seed_user.user_id),
            "type": "refresh",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_sub_claim_returns_401(self, client: AsyncClient):
        """Token without 'sub' claim should be rejected."""
        payload = {
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_sub_returns_401(self, client: AsyncClient):
        """Token with a non-UUID 'sub' claim should return 401, not 500."""
        payload = {
            "sub": "not-a-valid-uuid",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired token"

    @pytest.mark.asyncio
    async def test_nonexistent_user_id_returns_401(self, client: AsyncClient):
        """Token with a valid structure but non-existent user ID should be rejected."""
        token = make_valid_token(uuid.uuid4())
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_token_error_message(self, client: AsyncClient):
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header("x.y.z"))
        assert resp.json()["detail"] == "Invalid or expired token"

    @pytest.mark.asyncio
    async def test_www_authenticate_header_on_401(self, client: AsyncClient):
        """Verify 401 responses include WWW-Authenticate header."""
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header("bad"))
        assert resp.headers.get("www-authenticate") == "Bearer"


class TestInactiveUser:
    """Tokens for suspended/inactive users should be rejected with 403."""

    @pytest.mark.asyncio
    async def test_inactive_user_returns_403(self, client: AsyncClient, inactive_user):
        token = make_valid_token(inactive_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_user_error_message(self, client: AsyncClient, inactive_user):
        token = make_valid_token(inactive_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.json()["detail"] == "User account is not active"


class TestValidToken:
    """Requests with a valid token for an active user should succeed."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_200(self, client: AsyncClient, seed_user):
        token = make_valid_token(seed_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_token_returns_user_data(self, client: AsyncClient, seed_user):
        token = make_valid_token(seed_user.user_id)
        resp = await client.get(PROTECTED_ENDPOINT, headers=auth_header(token))
        data = resp.json()
        assert data["email"] == seed_user.email
        assert data["display_name"] == seed_user.display_name
        assert data["role"] == "client_admin"
        assert data["org_id"] == str(seed_user.org_id)
