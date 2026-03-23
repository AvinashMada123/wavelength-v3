"""Security tests: verify auth middleware cannot be bypassed.

Tests JWT authentication on real endpoints WITHOUT dependency overrides,
so the full auth chain (OAuth2PasswordBearer → decode_token → DB lookup)
is exercised. Each test attempts a different bypass technique and asserts
401 Unauthorized.

Uses the same SQLite test DB infrastructure as the leads integration tests.
"""

from __future__ import annotations

import base64
import json
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# SQLite ↔ PostgreSQL type shims (must be before model imports)
# ---------------------------------------------------------------------------

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"


from app.config import settings
from app.auth.security import create_access_token
from app.database import get_db
from app.models.bot_config import Base
from app.models.organization import Organization
from app.models.user import User

# Import all models for Base.metadata completeness
import app.models.billing  # noqa: F401
import app.models.call_analytics  # noqa: F401
import app.models.call_log  # noqa: F401
import app.models.call_queue  # noqa: F401
import app.models.campaign  # noqa: F401
import app.models.lead  # noqa: F401
import app.models.messaging_provider  # noqa: F401
import app.models.phone_number  # noqa: F401
import app.models.sequence  # noqa: F401
import app.models.user_org  # noqa: F401

# ---------------------------------------------------------------------------
# Test IDs and constants
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INACTIVE_USER_ID = uuid.uuid4()
WRONG_SECRET = "completely-wrong-secret-key"
PROTECTED_URL = "/api/leads"  # any endpoint that requires auth

# ---------------------------------------------------------------------------
# SQLite engine + session
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_defaults_sanitized = False


def _sanitize_defaults_for_sqlite(metadata):
    global _defaults_sanitized
    if _defaults_sanitized:
        return
    _defaults_sanitized = True

    import re
    import sqlalchemy as sa
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause
    from sqlalchemy.sql.elements import TextClause

    for table in metadata.tables.values():
        for col in table.columns:
            sd = col.server_default
            if sd is None or not isinstance(sd, DefaultClause):
                continue
            arg = sd.arg
            if isinstance(arg, TextClause):
                val = arg.text
            elif isinstance(arg, str):
                val = arg
            else:
                continue

            if "gen_random_uuid" in val:
                col.server_default = None
                if col.default is None:
                    col.default = sa.ColumnDefault(uuid.uuid4)
            elif "::jsonb" in val or "::json" in val:
                clean = re.sub(r"'([^']*)'\s*::\w+", r"'\1'", val)
                col.server_default = DefaultClause(sa_text(clean))
            elif "now()" in val:
                col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# Fixtures — NO auth dependency overrides (testing real auth)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    _sanitize_defaults_for_sqlite(Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        session.add(Organization(
            id=ORG_ID, name="Auth Test Org", slug="auth-test",
            plan="free", status="active", settings={}, usage={},
        ))
        await session.flush()

        # Active user — used to generate valid tokens
        session.add(User(
            id=USER_ID, email="active@example.com", display_name="Active User",
            password_hash="x", role="client_admin", org_id=ORG_ID,
            status="active", created_at=datetime.now(timezone.utc),
        ))
        # Inactive user — token is valid but account is disabled
        session.add(User(
            id=INACTIVE_USER_ID, email="inactive@example.com",
            display_name="Inactive User", password_hash="x",
            role="client_admin", org_id=ORG_ID, status="suspended",
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()

    yield

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    """Client with DB override but NO auth overrides — real auth is tested."""
    from app.main import app

    # Only override DB, NOT auth dependencies
    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


def _valid_token(user_id: uuid.UUID = USER_ID) -> str:
    """Generate a legitimately signed access token."""
    return create_access_token({"sub": str(user_id)})


# ===================================================================
# HEADER-LEVEL BYPASS ATTEMPTS
# ===================================================================


class TestMissingOrMalformedAuth:
    """Attempts to bypass auth at the HTTP header level."""

    @pytest.mark.asyncio
    async def test_no_authorization_header(self, client: AsyncClient):
        """Request with no Authorization header at all."""
        resp = await client.get(PROTECTED_URL)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_bearer_token(self, client: AsyncClient):
        """Authorization: Bearer (with no token after it)."""
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_with_only_spaces(self, client: AsyncClient):
        """Authorization: Bearer followed by whitespace."""
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": "Bearer    "},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_bearer_prefix(self, client: AsyncClient):
        """Token sent without 'Bearer ' prefix."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": token},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_auth_scheme(self, client: AsyncClient):
        """Using 'Basic' scheme instead of 'Bearer'."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Basic {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_in_query_string(self, client: AsyncClient):
        """Token passed as query parameter instead of header — must be rejected."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            params={"access_token": token},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_in_cookie(self, client: AsyncClient):
        """Token sent via cookie instead of header."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            cookies={"access_token": token},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_extra_spaces_in_bearer_prefix(self, client: AsyncClient):
        """'Bearer  <token>' with extra spaces between prefix and token."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer  {token}"},
        )
        # OAuth2PasswordBearer splits on "Bearer " — extra space becomes part of the token
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_lowercase_bearer(self, client: AsyncClient):
        """'bearer <token>' with lowercase b."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"bearer {token}"},
        )
        # FastAPI's OAuth2PasswordBearer is case-insensitive for the scheme,
        # so this may actually work. Either 200 or 401 is acceptable — the
        # critical thing is it doesn't bypass validation if it gets through.
        assert resp.status_code in (200, 401)


# ===================================================================
# TOKEN FORGERY / TAMPERING
# ===================================================================


class TestTokenForgery:
    """Attempts to forge or tamper with JWT tokens."""

    @pytest.mark.asyncio
    async def test_alg_none_attack(self, client: AsyncClient):
        """Classic JWT attack: set alg to 'none' with no signature.

        If the server accepts alg:none, an attacker can forge any token
        without knowing the secret.
        """
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({
                "sub": str(USER_ID),
                "type": "access",
                "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            }).encode()
        ).rstrip(b"=").decode()

        # alg:none token — header.payload. (empty signature)
        forged_token = f"{header}.{payload}."
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_alg_none_uppercase_variations(self, client: AsyncClient):
        """Try alg:None, alg:NONE, alg:nOnE — common bypass variants."""
        for alg in ["None", "NONE", "nOnE"]:
            header = base64.urlsafe_b64encode(
                json.dumps({"alg": alg, "typ": "JWT"}).encode()
            ).rstrip(b"=").decode()
            payload = base64.urlsafe_b64encode(
                json.dumps({
                    "sub": str(USER_ID),
                    "type": "access",
                    "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
                }).encode()
            ).rstrip(b"=").decode()

            forged = f"{header}.{payload}."
            resp = await client.get(
                PROTECTED_URL,
                headers={"Authorization": f"Bearer {forged}"},
            )
            assert resp.status_code == 401, f"alg:{alg} was not rejected"

    @pytest.mark.asyncio
    async def test_token_signed_with_wrong_secret(self, client: AsyncClient):
        """Token signed with a different HS256 secret — must be rejected."""
        forged = jwt.encode(
            {
                "sub": str(USER_ID),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            WRONG_SECRET,
            algorithm="HS256",
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_modified_payload_original_signature(self, client: AsyncClient):
        """Take a valid token, modify the payload (change user ID),
        but keep the original signature — must be rejected."""
        valid_token = _valid_token()
        parts = valid_token.split(".")
        assert len(parts) == 3

        # Decode payload, change sub to a different user
        payload_json = base64.urlsafe_b64decode(parts[1] + "==")
        payload_data = json.loads(payload_json)
        payload_data["sub"] = str(uuid.uuid4())  # different user

        # Re-encode payload but keep original header + signature
        tampered_payload = base64.urlsafe_b64encode(
            json.dumps(payload_data).encode()
        ).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_algorithm_confusion_hs384(self, client: AsyncClient):
        """Token signed with HS384 when server expects HS256."""
        forged = jwt.encode(
            {
                "sub": str(USER_ID),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm="HS384",
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_completely_garbage_token(self, client: AsyncClient):
        """Random string that isn't even valid base64 JWT structure."""
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": "Bearer not.a.jwt.at.all"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_truncated_token(self, client: AsyncClient):
        """Valid token with last 20 chars chopped off (corrupted signature)."""
        valid_token = _valid_token()
        truncated = valid_token[:-20]
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {truncated}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_base64_padding_on_signature(self, client: AsyncClient):
        """Extra base64 padding on signature — python-jose strips it and
        the signature still validates. This is safe (not a bypass) because
        the actual HMAC is unchanged. Verify it doesn't cause unexpected behavior."""
        valid_token = _valid_token()
        parts = valid_token.split(".")
        padded_token = f"{parts[0]}.{parts[1]}.{parts[2]}===="
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {padded_token}"},
        )
        # Signature is still valid after padding is stripped — 200 is acceptable
        assert resp.status_code in (200, 401)

    @pytest.mark.asyncio
    async def test_swapped_signature_from_different_token(self, client: AsyncClient):
        """Take header+payload from one token, signature from another."""
        token_a = _valid_token()
        # Create a different token (different exp will change the payload)
        token_b = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=2),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        parts_a = token_a.split(".")
        parts_b = token_b.split(".")
        # header+payload from A, signature from B
        franken_token = f"{parts_a[0]}.{parts_a[1]}.{parts_b[2]}"
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {franken_token}"},
        )
        assert resp.status_code == 401


# ===================================================================
# CLAIM-LEVEL BYPASS ATTEMPTS
# ===================================================================


class TestClaimBypass:
    """Attempts to bypass auth through valid-looking but incorrect claims."""

    @pytest.mark.asyncio
    async def test_expired_token(self, client: AsyncClient):
        """Token that expired 1 hour ago."""
        expired = jwt.encode(
            {
                "sub": str(USER_ID),
                "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_as_access(self, client: AsyncClient):
        """A valid refresh token should not work as an access token."""
        from app.auth.security import create_refresh_token

        refresh = create_refresh_token({"sub": str(USER_ID)})
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {refresh}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_sub_claim(self, client: AsyncClient):
        """Token with no 'sub' claim."""
        token = jwt.encode(
            {
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_type_claim(self, client: AsyncClient):
        """Token with sub but no 'type' claim."""
        token = jwt.encode(
            {
                "sub": str(USER_ID),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_sub(self, client: AsyncClient):
        """Token with a non-UUID value in the 'sub' claim."""
        token = jwt.encode(
            {
                "sub": "not-a-uuid",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_user_id(self, client: AsyncClient):
        """Valid token structure but sub points to a user that doesn't exist."""
        token = create_access_token({"sub": str(uuid.uuid4())})
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_403(self, client: AsyncClient):
        """Valid token for a suspended user should return 403, not 200."""
        token = create_access_token({"sub": str(INACTIVE_USER_ID)})
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"]


# ===================================================================
# SANITY CHECK — valid token works
# ===================================================================


class TestValidAuth:
    """Confirm that a properly formed token actually succeeds."""

    @pytest.mark.asyncio
    async def test_valid_token_succeeds(self, client: AsyncClient):
        """Baseline: a correctly signed, non-expired token for an active user works."""
        token = _valid_token()
        resp = await client.get(
            PROTECTED_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# ===================================================================
# REFRESH ENDPOINT SECURITY
# ===================================================================


class TestRefreshEndpoint:
    """POST /api/auth/refresh — verify user status is checked on refresh."""

    @pytest.mark.asyncio
    async def test_refresh_valid_token_succeeds(self, client: AsyncClient):
        """Active user with valid refresh token gets a new access token."""
        from app.auth.security import create_refresh_token

        refresh = create_refresh_token({"sub": str(USER_ID)})
        resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    @pytest.mark.asyncio
    async def test_refresh_suspended_user_403(self, client: AsyncClient):
        """Suspended user cannot refresh — even with a valid refresh token."""
        from app.auth.security import create_refresh_token

        refresh = create_refresh_token({"sub": str(INACTIVE_USER_ID)})
        resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_deleted_user_401(self, client: AsyncClient):
        """Refresh token for a user that no longer exists in DB."""
        from app.auth.security import create_refresh_token

        refresh = create_refresh_token({"sub": str(uuid.uuid4())})
        resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 401
        assert "no longer exists" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, client: AsyncClient):
        """An access token should not work as a refresh token."""
        access = create_access_token({"sub": str(USER_ID)})
        resp = await client.post("/api/auth/refresh", json={"refresh_token": access})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_expired_token_rejected(self, client: AsyncClient):
        """Expired refresh token should be rejected."""
        expired = jwt.encode(
            {
                "sub": str(USER_ID),
                "type": "refresh",
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = await client.post("/api/auth/refresh", json={"refresh_token": expired})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_garbage_token_rejected(self, client: AsyncClient):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401
