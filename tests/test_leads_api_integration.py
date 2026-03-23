"""Integration tests for /api/leads endpoints.

Uses an in-memory SQLite database via SQLAlchemy async, overriding the
FastAPI dependency injection so every test hits a real (ephemeral) DB.

Covers: success responses, validation errors, 404s, 409 duplicates,
pagination, search/filter, bulk import, org-scoping, lead calls,
JSON field round-trips, and edge cases.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# SQLite ↔ PostgreSQL type compatibility shims
# Register custom DDL compilers for SQLite BEFORE importing models.
# ---------------------------------------------------------------------------

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"


from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.bot_config import Base, BotConfig
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.user import User

# Import all models so Base.metadata has every table (avoids FK resolution errors)
import app.models.billing  # noqa: F401
import app.models.call_analytics  # noqa: F401
import app.models.call_queue  # noqa: F401
import app.models.campaign  # noqa: F401
import app.models.messaging_provider  # noqa: F401
import app.models.phone_number  # noqa: F401
import app.models.sequence  # noqa: F401
import app.models.user_org  # noqa: F401

# ---------------------------------------------------------------------------
# Shared IDs for seed data
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
BOT_ID = uuid.uuid4()
LEAD_A_ID = uuid.uuid4()
LEAD_B_ID = uuid.uuid4()
CHARLIE_ID = uuid.uuid4()  # Lead in OTHER_ORG — used for cross-org isolation tests
CALL_LOG_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# SQLite-compatible async engine
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    """Enable WAL + foreign keys for SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# PG → SQLite default sanitization (runs once)
# ---------------------------------------------------------------------------

_defaults_sanitized = False


def _sanitize_defaults_for_sqlite(metadata):
    """Strip PostgreSQL-specific server_defaults that SQLite cannot compile.

    Idempotent — skips if already run (guarded by module-level flag).
    """
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


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_org(org_id: uuid.UUID, name: str, slug: str) -> Organization:
    return Organization(
        id=org_id, name=name, slug=slug,
        plan="free", status="active", settings={}, usage={},
    )


def _make_user() -> User:
    return User(
        id=USER_ID, email="test@example.com", display_name="Test User",
        password_hash="not-a-real-hash", role="client_admin",
        org_id=ORG_ID, status="active", created_at=datetime.now(timezone.utc),
    )


def _make_bot() -> BotConfig:
    return BotConfig(
        id=BOT_ID, agent_name="Test Bot", company_name="Test Co",
        system_prompt_template="You are a test bot.",
        org_id=ORG_ID,
    )


def _seed_leads() -> list[Lead]:
    """Two leads in ORG_ID + one in OTHER_ORG_ID for isolation checks."""
    now = datetime.now(timezone.utc)
    return [
        Lead(
            id=LEAD_A_ID, org_id=ORG_ID, phone_number="+11111111111",
            contact_name="Alice", email="alice@example.com", company="Acme",
            tags=[], custom_fields={}, status="new", call_count=0,
            source="manual", created_by=USER_ID, created_at=now, updated_at=now,
        ),
        Lead(
            id=LEAD_B_ID, org_id=ORG_ID, phone_number="+12222222222",
            contact_name="Bob", email="bob@example.com", company="Globex",
            tags=["vip"], custom_fields={"tier": "gold"}, status="contacted",
            call_count=2, source="import", created_by=USER_ID,
            created_at=now, updated_at=now,
        ),
        Lead(
            id=CHARLIE_ID, org_id=OTHER_ORG_ID, phone_number="+13333333333",
            contact_name="Charlie (other org)", tags=[], custom_fields={},
            status="new", call_count=0, source="manual", created_by=None,
            created_at=now, updated_at=now,
        ),
    ]


def _make_call_log(lead_phone: str) -> CallLog:
    """Create a call log matching a lead's phone number."""
    return CallLog(
        id=CALL_LOG_ID, org_id=ORG_ID, bot_id=BOT_ID,
        call_sid=f"test-sid-{uuid.uuid4().hex[:8]}",
        contact_name="Alice", contact_phone=lead_phone,
        status="completed", outcome="success", call_duration=120,
        summary="Test call", created_at=datetime.now(timezone.utc),
        metadata_={},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    """Create all tables, seed, then tear down after each test."""
    _sanitize_defaults_for_sqlite(Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed data — respect FK ordering: orgs → bot → user → leads → call_logs
    async with TestSessionLocal() as session:
        session.add(_make_org(ORG_ID, "Test Org", "test-org"))
        session.add(_make_org(OTHER_ORG_ID, "Other Org", "other-org"))
        await session.flush()

        session.add(_make_bot())
        session.add(_make_user())
        await session.flush()

        for lead in _seed_leads():
            session.add(lead)
        await session.flush()

        # One call log for Alice's phone number
        session.add(_make_call_log("+11111111111"))
        await session.commit()

    yield

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


async def _override_get_current_user() -> User:
    """Return a fake User without touching the DB or JWT."""
    return User(
        id=USER_ID, email="test@example.com", display_name="Test User",
        password_hash="x", role="client_admin", org_id=ORG_ID,
        status="active", created_at=datetime.now(timezone.utc),
    )


async def _override_get_current_org() -> uuid.UUID:
    return ORG_ID


@pytest_asyncio.fixture
async def client():
    """Async httpx client wired to the FastAPI app with overridden deps."""
    from app.main import app

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_current_org] = _override_get_current_org

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ===================================================================
# LIST LEADS
# ===================================================================


class TestListLeads:
    """GET /api/leads"""

    @pytest.mark.asyncio
    async def test_returns_paginated_leads(self, client: AsyncClient):
        resp = await client.get("/api/leads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # only ORG_ID leads
        assert data["page"] == 1
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"status": "contacted"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["contact_name"] == "Bob"

    @pytest.mark.asyncio
    async def test_filter_by_nonexistent_status(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"status": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_search_by_name(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"search": "alice"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["contact_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_search_by_phone(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"search": "+1111"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_search_by_email(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"search": "bob@example"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_search_with_sql_wildcards(self, client: AsyncClient):
        """SQL wildcards in search input should not produce unexpected matches."""
        resp = await client.get("/api/leads", params={"search": "%"})
        # '%' wrapped as '%%' → matches everything in the org (2 leads)
        # This documents current (unescaped) behavior — not ideal but explicit.
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_pagination_page_1(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"page": 1, "page_size": 1})
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 1
        assert data["page_size"] == 1

    @pytest.mark.asyncio
    async def test_pagination_page_2(self, client: AsyncClient):
        """Page 2 should return the other lead."""
        resp = await client.get("/api/leads", params={"page": 2, "page_size": 1})
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 1
        assert data["page"] == 2

    @pytest.mark.asyncio
    async def test_pagination_beyond_last_page(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"page": 99, "page_size": 50})
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 0

    @pytest.mark.asyncio
    async def test_page_size_validation_too_large(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"page_size": 999})
        assert resp.status_code == 422  # exceeds max 200

    @pytest.mark.asyncio
    async def test_page_zero_validation(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"page": 0})
        assert resp.status_code == 422  # ge=1

    @pytest.mark.asyncio
    async def test_negative_page_validation(self, client: AsyncClient):
        resp = await client.get("/api/leads", params={"page": -1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_org_isolation(self, client: AsyncClient):
        """Leads from OTHER_ORG_ID must never appear."""
        resp = await client.get("/api/leads", params={"search": "Charlie"})
        assert resp.json()["total"] == 0


# ===================================================================
# CREATE LEAD
# ===================================================================


class TestCreateLead:
    """POST /api/leads"""

    @pytest.mark.asyncio
    async def test_create_success(self, client: AsyncClient):
        payload = {
            "phone_number": "+19999999999",
            "contact_name": "New Lead",
            "email": "new@example.com",
            "company": "NewCo",
        }
        resp = await client.post("/api/leads", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["phone_number"] == "+19999999999"
        assert data["contact_name"] == "New Lead"
        assert data["status"] == "new"
        assert data["source"] == "manual"
        assert data["org_id"] == str(ORG_ID)

    @pytest.mark.asyncio
    async def test_create_minimal_fields(self, client: AsyncClient):
        """Only phone_number and contact_name are required."""
        resp = await client.post(
            "/api/leads",
            json={"phone_number": "+18888888888", "contact_name": "Minimal"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_with_custom_fields_roundtrip(self, client: AsyncClient):
        """JSON fields (tags, custom_fields) survive the write → read cycle."""
        payload = {
            "phone_number": "+18765432100",
            "contact_name": "JSON Test",
            "tags": ["hot", "enterprise"],
            "custom_fields": {"revenue": 50000, "notes": "Important client"},
        }
        resp = await client.post("/api/leads", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["tags"] == ["hot", "enterprise"]
        assert data["custom_fields"]["revenue"] == 50000

        # Verify via GET
        lead_id = data["id"]
        resp2 = await client.get(f"/api/leads/{lead_id}")
        assert resp2.status_code == 200
        assert resp2.json()["tags"] == ["hot", "enterprise"]
        assert resp2.json()["custom_fields"]["notes"] == "Important client"

    @pytest.mark.asyncio
    async def test_create_missing_required_fields(self, client: AsyncClient):
        resp = await client.post("/api/leads", json={"phone_number": "+10000000000"})
        assert resp.status_code == 422  # contact_name missing

    @pytest.mark.asyncio
    async def test_create_empty_body(self, client: AsyncClient):
        resp = await client.post("/api/leads", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_duplicate_phone_409(self, client: AsyncClient):
        """Duplicate phone within same org returns 409."""
        resp = await client.post(
            "/api/leads",
            json={"phone_number": "+11111111111", "contact_name": "Dup"},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_persists_in_db(self, client: AsyncClient):
        """Created lead shows up in subsequent list."""
        await client.post(
            "/api/leads",
            json={"phone_number": "+17777777777", "contact_name": "Persist"},
        )
        resp = await client.get("/api/leads", params={"search": "Persist"})
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_create_after_delete_same_phone(self, client: AsyncClient):
        """After deleting a lead, re-creating with same phone should succeed."""
        resp = await client.delete(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 204

        resp = await client.post(
            "/api/leads",
            json={"phone_number": "+11111111111", "contact_name": "Alice Reborn"},
        )
        assert resp.status_code == 201
        assert resp.json()["contact_name"] == "Alice Reborn"


# ===================================================================
# GET SINGLE LEAD
# ===================================================================


class TestGetLead:
    """GET /api/leads/{lead_id}"""

    @pytest.mark.asyncio
    async def test_get_success(self, client: AsyncClient):
        resp = await client.get(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 200
        assert resp.json()["contact_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_nonexistent_404(self, client: AsyncClient):
        resp = await client.get(f"/api/leads/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Lead not found"

    @pytest.mark.asyncio
    async def test_get_other_org_lead_404(self, client: AsyncClient):
        """A lead belonging to another org should 404 (not 403) for our user."""
        resp = await client.get(f"/api/leads/{CHARLIE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_invalid_uuid_422(self, client: AsyncClient):
        """Non-UUID path parameter should return 422."""
        resp = await client.get("/api/leads/not-a-uuid")
        assert resp.status_code == 422


# ===================================================================
# UPDATE LEAD
# ===================================================================


class TestUpdateLead:
    """PUT /api/leads/{lead_id}"""

    @pytest.mark.asyncio
    async def test_update_success(self, client: AsyncClient):
        resp = await client.put(
            f"/api/leads/{LEAD_A_ID}",
            json={"contact_name": "Alice Updated", "status": "qualified"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contact_name"] == "Alice Updated"
        assert data["status"] == "qualified"
        assert data["phone_number"] == "+11111111111"  # unchanged

    @pytest.mark.asyncio
    async def test_update_single_field(self, client: AsyncClient):
        resp = await client.put(
            f"/api/leads/{LEAD_B_ID}",
            json={"company": "Globex Corp"},
        )
        assert resp.status_code == 200
        assert resp.json()["company"] == "Globex Corp"

    @pytest.mark.asyncio
    async def test_update_json_fields(self, client: AsyncClient):
        """Updating tags and custom_fields should merge correctly."""
        resp = await client.put(
            f"/api/leads/{LEAD_B_ID}",
            json={
                "tags": ["vip", "renewed"],
                "custom_fields": {"tier": "platinum", "discount": 10},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == ["vip", "renewed"]
        assert data["custom_fields"]["tier"] == "platinum"
        assert data["custom_fields"]["discount"] == 10

    @pytest.mark.asyncio
    async def test_update_nonexistent_404(self, client: AsyncClient):
        resp = await client.put(
            f"/api/leads/{uuid.uuid4()}",
            json={"contact_name": "Ghost"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_other_org_lead_404(self, client: AsyncClient):
        """Updating a lead from another org should 404."""
        resp = await client.put(
            f"/api/leads/{CHARLIE_ID}",
            json={"contact_name": "Hacked"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_empty_body_no_op(self, client: AsyncClient):
        """Empty update body should succeed but change nothing."""
        resp = await client.put(f"/api/leads/{LEAD_A_ID}", json={})
        assert resp.status_code == 200
        assert resp.json()["contact_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_update_invalid_uuid_422(self, client: AsyncClient):
        resp = await client.put("/api/leads/bad-id", json={"contact_name": "X"})
        assert resp.status_code == 422


# ===================================================================
# DELETE LEAD
# ===================================================================


class TestDeleteLead:
    """DELETE /api/leads/{lead_id}"""

    @pytest.mark.asyncio
    async def test_delete_success(self, client: AsyncClient):
        resp = await client.delete(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 204

        # Confirm gone
        resp = await client.get(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_reduces_count(self, client: AsyncClient):
        """List total should decrease after deletion."""
        resp = await client.get("/api/leads")
        before = resp.json()["total"]

        await client.delete(f"/api/leads/{LEAD_A_ID}")

        resp = await client.get("/api/leads")
        assert resp.json()["total"] == before - 1

    @pytest.mark.asyncio
    async def test_delete_nonexistent_404(self, client: AsyncClient):
        resp = await client.delete(f"/api/leads/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_other_org_lead_404(self, client: AsyncClient):
        """Cannot delete a lead from another org."""
        resp = await client.delete(f"/api/leads/{CHARLIE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_idempotent_second_call_404(self, client: AsyncClient):
        """Deleting the same lead twice should 404 the second time."""
        resp = await client.delete(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 204

        resp = await client.delete(f"/api/leads/{LEAD_A_ID}")
        assert resp.status_code == 404


# ===================================================================
# GET LEAD CALLS
# ===================================================================


class TestGetLeadCalls:
    """GET /api/leads/{lead_id}/calls"""

    @pytest.mark.asyncio
    async def test_get_calls_success(self, client: AsyncClient):
        """Alice has one call log seeded — should return it."""
        resp = await client.get(f"/api/leads/{LEAD_A_ID}/calls")
        assert resp.status_code == 200
        calls = resp.json()
        assert len(calls) == 1
        assert calls[0]["contact_phone"] == "+11111111111"
        assert calls[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_calls_empty(self, client: AsyncClient):
        """Bob has no call logs — should return empty list."""
        resp = await client.get(f"/api/leads/{LEAD_B_ID}/calls")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_calls_nonexistent_lead_404(self, client: AsyncClient):
        resp = await client.get(f"/api/leads/{uuid.uuid4()}/calls")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_calls_other_org_lead_404(self, client: AsyncClient):
        resp = await client.get(f"/api/leads/{CHARLIE_ID}/calls")
        assert resp.status_code == 404


# ===================================================================
# BULK IMPORT
# ===================================================================


class TestBulkImport:
    """POST /api/leads/import"""

    @pytest.mark.asyncio
    async def test_import_success(self, client: AsyncClient):
        payload = {
            "leads": [
                {"phone_number": "+14444444444", "contact_name": "Import1"},
                {"phone_number": "+15555555555", "contact_name": "Import2"},
            ]
        }
        resp = await client.post("/api/leads/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_import_persists_in_db(self, client: AsyncClient):
        """Imported leads should be queryable via the list endpoint."""
        await client.post(
            "/api/leads/import",
            json={"leads": [{"phone_number": "+14444444444", "contact_name": "Import1"}]},
        )
        resp = await client.get("/api/leads", params={"search": "Import1"})
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_import_skips_existing(self, client: AsyncClient):
        """Phone numbers that already exist in org are skipped."""
        payload = {
            "leads": [
                {"phone_number": "+11111111111", "contact_name": "Dup Alice"},
                {"phone_number": "+16666666666", "contact_name": "Fresh"},
            ]
        }
        resp = await client.post("/api/leads/import", json=payload)
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_import_skips_within_batch_duplicates(self, client: AsyncClient):
        """Duplicate phone numbers within the same batch are de-duped."""
        payload = {
            "leads": [
                {"phone_number": "+17070707070", "contact_name": "First"},
                {"phone_number": "+17070707070", "contact_name": "Second"},
            ]
        }
        resp = await client.post("/api/leads/import", json=payload)
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_import_empty_list(self, client: AsyncClient):
        resp = await client.post("/api/leads/import", json={"leads": []})
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0

    @pytest.mark.asyncio
    async def test_import_validation_error(self, client: AsyncClient):
        """Missing required fields in import items should 422."""
        resp = await client.post(
            "/api/leads/import",
            json={"leads": [{"phone_number": "+10000000000"}]},  # no contact_name
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_import_all_duplicates(self, client: AsyncClient):
        """Importing only existing phones results in 0 imported, N skipped."""
        payload = {
            "leads": [
                {"phone_number": "+11111111111", "contact_name": "Dup1"},
                {"phone_number": "+12222222222", "contact_name": "Dup2"},
            ]
        }
        resp = await client.post("/api/leads/import", json=payload)
        data = resp.json()
        assert data["imported"] == 0
        assert data["skipped"] == 2
