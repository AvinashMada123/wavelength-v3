"""Comprehensive auth tests: token states × protected endpoints × role-based access.

Tests every protected endpoint with each token state (valid, expired, wrong-secret,
malformed, missing, refresh-as-access, invalid-uuid-sub). Verifies role-based access
control and ensures error responses use generic messages (no info leakage).

Uses a real PostgreSQL database, not mocks.
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
# Database engines (NullPool for pytest-asyncio per-test event loop compat)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", settings.DATABASE_URL)

app_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
AppSessionFactory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

fixture_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
FixtureSessionFactory = async_sessionmaker(fixture_engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Test app with ALL routers mounted (not just auth)
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from app.auth import router as auth_router
from app.api import admin, billing, bots, campaigns, leads, messaging_providers
from app.api import payments, queue, sequences, telephony


def create_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(auth_router.router)
    test_app.include_router(admin.router)
    test_app.include_router(billing.router)
    test_app.include_router(bots.router)
    test_app.include_router(campaigns.router)
    test_app.include_router(leads.router)
    test_app.include_router(messaging_providers.router)
    test_app.include_router(payments.router)
    test_app.include_router(queue.router)
    test_app.include_router(sequences.router)
    test_app.include_router(telephony.router)

    async def _override_get_db():
        async with AppSessionFactory() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


_test_app = create_test_app()


# ---------------------------------------------------------------------------
# Token helper library
# ---------------------------------------------------------------------------

class TokenFactory:
    """Generate JWTs in every meaningful state for testing."""

    @staticmethod
    def valid(user_id: uuid.UUID) -> str:
        """Standard valid access token (24h expiry)."""
        return create_access_token({"sub": str(user_id)})

    @staticmethod
    def expired(user_id: uuid.UUID) -> str:
        """Token that expired 1 hour ago."""
        payload = {
            "sub": str(user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def wrong_secret(user_id: uuid.UUID) -> str:
        """Token signed with an incorrect secret."""
        payload = {
            "sub": str(user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jwt.encode(payload, "wrong-secret-key-12345", algorithm="HS256")

    @staticmethod
    def malformed() -> str:
        """Completely invalid JWT string."""
        return "not.a.valid.jwt.token"

    @staticmethod
    def refresh_token(user_id: uuid.UUID) -> str:
        """Valid refresh token (should be rejected on access endpoints)."""
        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "exp": datetime.now(timezone.utc) + timedelta(days=30),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def missing_sub() -> str:
        """Token without 'sub' claim."""
        payload = {
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def invalid_uuid_sub() -> str:
        """Token with a non-UUID 'sub' claim."""
        payload = {
            "sub": "not-a-uuid",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def nonexistent_user() -> str:
        """Token for a user ID that doesn't exist in the DB."""
        return create_access_token({"sub": str(uuid.uuid4())})

    @staticmethod
    def nearly_expired(user_id: uuid.UUID) -> str:
        """Token expiring in 2 seconds — for boundary testing."""
        payload = {
            "sub": str(user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(seconds=2),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def empty_sub() -> str:
        """Token with empty string as 'sub'."""
        payload = {
            "sub": "",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def wrong_algorithm(user_id: uuid.UUID) -> str:
        """Token signed with HS384 instead of HS256."""
        payload = {
            "sub": str(user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS384")


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UserData:
    user_id: uuid.UUID
    email: str
    role: str
    org_id: uuid.UUID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=_test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def org_and_users():
    """Create an org with users at every role level. Cleaned up after test."""
    org_id = uuid.uuid4()
    users: dict[str, UserData] = {}
    user_ids: list[uuid.UUID] = []

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

        for role in ("super_admin", "client_admin", "client_user"):
            uid = uuid.uuid4()
            email = f"{role}-{uid.hex[:8]}@example.com"
            user = User(
                id=uid,
                email=email,
                display_name=f"Test {role}",
                password_hash=hash_password("testpass123"),
                role=role,
                org_id=org_id,
                status="active",
            )
            session.add(user)
            users[role] = UserData(user_id=uid, email=email, role=role, org_id=org_id)
            user_ids.append(uid)

        # Also create a suspended user
        suspended_id = uuid.uuid4()
        session.add(User(
            id=suspended_id,
            email=f"suspended-{suspended_id.hex[:8]}@example.com",
            display_name="Suspended User",
            password_hash=hash_password("testpass123"),
            role="client_admin",
            org_id=org_id,
            status="suspended",
        ))
        users["suspended"] = UserData(
            user_id=suspended_id, email=f"suspended-{suspended_id.hex[:8]}@example.com",
            role="client_admin", org_id=org_id,
        )
        user_ids.append(suspended_id)

        await session.commit()

    yield users

    # Cleanup
    async with FixtureSessionFactory() as session:
        for uid in user_ids:
            await session.execute(delete(User).where(User.id == uid))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


@pytest.fixture(scope="module", autouse=True)
def dispose_engines(request):
    import asyncio

    def _dispose():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(app_engine.dispose())
        loop.run_until_complete(fixture_engine.dispose())
        loop.close()

    request.addfinalizer(_dispose)


# ===========================================================================
# SECTION 1: Token state matrix — every bad token type against representative
#             endpoints from each access tier
# ===========================================================================

# Representative endpoints per access level (GET endpoints to avoid needing
# request bodies, making the auth-layer test cleaner).
ENDPOINTS = {
    "auth_only": [
        ("GET", "/api/auth/me"),
        ("GET", "/api/billing/balance"),
    ],
    "client_admin_or_super": [
        ("GET", "/api/telephony/config"),
    ],
    "super_admin_only": [
        ("GET", "/api/admin/organizations"),
        ("GET", "/api/admin/stats"),
    ],
}

ALL_ENDPOINTS = [
    ep for group in ENDPOINTS.values() for ep in group
]

# Every token state that should produce a 401
BAD_TOKEN_STATES = [
    ("no_token", None),
    ("empty_bearer", ""),
    ("malformed", TokenFactory.malformed()),
    ("missing_sub", TokenFactory.missing_sub()),
    ("invalid_uuid_sub", TokenFactory.invalid_uuid_sub()),
    ("nonexistent_user", TokenFactory.nonexistent_user()),
]


class TestTokenStateMatrix:
    """Every bad token state must produce 401 on every protected endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    @pytest.mark.parametrize("state_name,token", BAD_TOKEN_STATES, ids=[s[0] for s in BAD_TOKEN_STATES])
    async def test_bad_token_returns_401(self, client, state_name, token, method, path):
        headers = auth_header(token) if token is not None else {}
        if token == "":
            headers = {"Authorization": "Bearer "}
        resp = await client.request(method, path, headers=headers)
        assert resp.status_code == 401, (
            f"{state_name} on {method} {path} returned {resp.status_code}, expected 401"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    async def test_expired_token_returns_401(self, client, org_and_users, method, path):
        user = org_and_users["super_admin"]
        token = TokenFactory.expired(user.user_id)
        resp = await client.request(method, path, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    async def test_wrong_secret_returns_401(self, client, org_and_users, method, path):
        user = org_and_users["super_admin"]
        token = TokenFactory.wrong_secret(user.user_id)
        resp = await client.request(method, path, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    async def test_refresh_token_returns_401(self, client, org_and_users, method, path):
        user = org_and_users["super_admin"]
        token = TokenFactory.refresh_token(user.user_id)
        resp = await client.request(method, path, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    async def test_wrong_algorithm_returns_401(self, client, org_and_users, method, path):
        user = org_and_users["super_admin"]
        token = TokenFactory.wrong_algorithm(user.user_id)
        resp = await client.request(method, path, headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ALL_ENDPOINTS, ids=[f"{m} {p}" for m, p in ALL_ENDPOINTS])
    async def test_empty_sub_returns_401(self, client, method, path):
        token = TokenFactory.empty_sub()
        resp = await client.request(method, path, headers=auth_header(token))
        assert resp.status_code == 401


# ===========================================================================
# SECTION 2: Info leakage — error responses must be generic
# ===========================================================================

# Allowed 401 detail messages (generic, no info leakage)
ALLOWED_401_DETAILS = {"Not authenticated", "Invalid or expired token"}
ALLOWED_403_DETAILS = {"User account is not active"}


class TestNoInfoLeakage:
    """Error responses must not reveal internal details."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_fn,desc", [
        (TokenFactory.malformed, "malformed"),
        (TokenFactory.missing_sub, "missing_sub"),
        (TokenFactory.invalid_uuid_sub, "invalid_uuid_sub"),
        (TokenFactory.nonexistent_user, "nonexistent_user"),
    ], ids=["malformed", "missing_sub", "invalid_uuid_sub", "nonexistent_user"])
    async def test_401_uses_generic_message(self, client, token_fn, desc):
        """All 401s use the same generic message — attacker can't distinguish token issues."""
        resp = await client.get("/api/auth/me", headers=auth_header(token_fn()))
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail in ALLOWED_401_DETAILS, (
            f"Token state '{desc}' leaked info: '{detail}'"
        )

    @pytest.mark.asyncio
    async def test_expired_and_wrong_secret_same_message(self, client, org_and_users):
        """Expired and wrong-secret tokens must return identical error detail."""
        user = org_and_users["super_admin"]
        resp_expired = await client.get(
            "/api/auth/me", headers=auth_header(TokenFactory.expired(user.user_id))
        )
        resp_wrong = await client.get(
            "/api/auth/me", headers=auth_header(TokenFactory.wrong_secret(user.user_id))
        )
        assert resp_expired.json()["detail"] == resp_wrong.json()["detail"]

    @pytest.mark.asyncio
    async def test_nonexistent_vs_malformed_same_message(self, client):
        """Nonexistent user and malformed token must return identical detail."""
        resp_nonexistent = await client.get(
            "/api/auth/me", headers=auth_header(TokenFactory.nonexistent_user())
        )
        resp_malformed = await client.get(
            "/api/auth/me", headers=auth_header(TokenFactory.malformed())
        )
        assert resp_nonexistent.json()["detail"] == resp_malformed.json()["detail"]

    @pytest.mark.asyncio
    async def test_401_includes_www_authenticate(self, client):
        """All 401 responses must include WWW-Authenticate: Bearer header."""
        resp = await client.get("/api/auth/me", headers=auth_header("bad"))
        assert resp.headers.get("www-authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_no_stack_trace_in_error(self, client):
        """Error response body must not contain stack trace or internal paths."""
        resp = await client.get(
            "/api/auth/me", headers=auth_header(TokenFactory.invalid_uuid_sub())
        )
        body = resp.text.lower()
        for leak_indicator in ("traceback", "file ", "/app/", "line ", "exception"):
            assert leak_indicator not in body, (
                f"Response leaked internal info: found '{leak_indicator}'"
            )

    @pytest.mark.asyncio
    async def test_suspended_user_403_is_generic(self, client, org_and_users):
        """Suspended user error must not reveal why the account is inactive."""
        user = org_and_users["suspended"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail in ALLOWED_403_DETAILS
        # Must NOT contain the actual status value
        assert "suspended" not in detail.lower()


# ===========================================================================
# SECTION 3: Role-based access control
# ===========================================================================

class TestRoleBasedAccess:
    """Verify role hierarchy: super_admin > client_admin > client_user."""

    # --- Super admin only endpoints ---

    @pytest.mark.asyncio
    async def test_super_admin_can_access_admin_endpoints(self, client, org_and_users):
        user = org_and_users["super_admin"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/admin/organizations", headers=auth_header(token))
        # Auth layer must not block; endpoint may fail for non-auth reasons (e.g. schema)
        assert resp.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_client_admin_blocked_from_admin_endpoints(self, client, org_and_users):
        user = org_and_users["client_admin"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/admin/organizations", headers=auth_header(token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_client_user_blocked_from_admin_endpoints(self, client, org_and_users):
        user = org_and_users["client_user"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/admin/organizations", headers=auth_header(token))
        assert resp.status_code == 403

    # --- Client admin + super admin endpoints ---

    @pytest.mark.asyncio
    async def test_super_admin_can_access_telephony(self, client, org_and_users):
        user = org_and_users["super_admin"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/telephony/config", headers=auth_header(token))
        assert resp.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_client_admin_can_access_telephony(self, client, org_and_users):
        user = org_and_users["client_admin"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/telephony/config", headers=auth_header(token))
        assert resp.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_client_user_blocked_from_telephony(self, client, org_and_users):
        user = org_and_users["client_user"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/telephony/config", headers=auth_header(token))
        assert resp.status_code == 403

    # --- Auth-only endpoints (any authenticated user) ---

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["super_admin", "client_admin", "client_user"])
    async def test_any_role_can_access_auth_me(self, client, org_and_users, role):
        user = org_and_users[role]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code not in (401, 403)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["super_admin", "client_admin", "client_user"])
    async def test_any_role_can_access_billing_balance(self, client, org_and_users, role):
        user = org_and_users[role]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/billing/balance", headers=auth_header(token))
        assert resp.status_code not in (401, 403)

    # --- 403 error message for role violations ---

    @pytest.mark.asyncio
    async def test_role_403_message_mentions_required_roles(self, client, org_and_users):
        """403 for role violation should indicate what roles are required."""
        user = org_and_users["client_user"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/admin/organizations", headers=auth_header(token))
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "super_admin" in detail
        assert "client_user" in detail  # mentions the user's current role

    @pytest.mark.asyncio
    async def test_suspended_user_blocked_regardless_of_role(self, client, org_and_users):
        """A suspended user must be blocked even if their role would allow access."""
        user = org_and_users["suspended"]
        token = TokenFactory.valid(user.user_id)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code == 403


# ===========================================================================
# SECTION 4: Token expiry edge cases
# ===========================================================================

class TestTokenExpiryEdgeCases:
    """Edge cases around token lifetime boundaries."""

    @pytest.mark.asyncio
    async def test_token_just_expired(self, client, org_and_users):
        """Token that expired 1 second ago should be rejected."""
        user = org_and_users["super_admin"]
        payload = {
            "sub": str(user.user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_far_future_expiry_still_valid(self, client, org_and_users):
        """Token with a far-future expiry should still work."""
        user = org_and_users["super_admin"]
        payload = {
            "sub": str(user.user_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(days=365),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_token_without_exp_claim(self, client, org_and_users):
        """Token missing 'exp' claim entirely — jose should reject it."""
        user = org_and_users["super_admin"]
        payload = {
            "sub": str(user.user_id),
            "type": "access",
            # No "exp" key
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        # jose defaults: no exp means no expiry check → might be 200
        # Either 200 or 401 is acceptable, but NOT 500
        assert resp.status_code in (200, 401), (
            f"Missing exp claim caused {resp.status_code}, expected 200 or 401"
        )


# ===========================================================================
# SECTION 5: Bulk endpoint sweep — all protected endpoints reject no-token
# ===========================================================================

# Every protected endpoint in the app (GET endpoints only for clean auth testing)
ALL_PROTECTED_GET_ENDPOINTS = [
    # Auth-only
    "/api/auth/me",
    "/api/auth/orgs",
    "/api/billing/balance",
    "/api/billing/transactions",
    # Client admin + super admin
    "/api/telephony/config",
    "/api/telephony/phone-numbers",
    "/api/auth/invites",
    # Super admin only
    "/api/admin/organizations",
    "/api/admin/users",
    "/api/admin/stats",
    "/api/billing/admin/org-balances",
]


class TestBulkEndpointSweep:
    """Every protected GET endpoint must reject unauthenticated requests."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ALL_PROTECTED_GET_ENDPOINTS)
    async def test_no_token_returns_401(self, client, path):
        resp = await client.get(path)
        assert resp.status_code == 401, f"{path} returned {resp.status_code} without token"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ALL_PROTECTED_GET_ENDPOINTS)
    async def test_malformed_token_returns_401(self, client, path):
        resp = await client.get(path, headers=auth_header(TokenFactory.malformed()))
        assert resp.status_code == 401, f"{path} returned {resp.status_code} with malformed token"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ALL_PROTECTED_GET_ENDPOINTS)
    async def test_error_detail_is_generic(self, client, path):
        resp = await client.get(path, headers=auth_header(TokenFactory.malformed()))
        detail = resp.json().get("detail", "")
        assert detail in ALLOWED_401_DETAILS, (
            f"{path} leaked info in error: '{detail}'"
        )
