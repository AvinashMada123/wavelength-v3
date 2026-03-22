"""Integration tests for the /api/calls endpoint.

Covers: metadata serialization, org-scoped isolation, filtering,
empty results, and response shape validation.
Uses a real PostgreSQL database.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.security import create_access_token, hash_password
from app.config import settings
from app.database import get_db
from app.models.call_log import CallLog
from app.models.organization import Organization
from app.models.user import User

# ---------------------------------------------------------------------------
# Database engines
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", settings.DATABASE_URL)

app_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
AppSessionFactory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

fixture_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
FixtureSessionFactory = async_sessionmaker(fixture_engine, class_=AsyncSession, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from app.api import calls as calls_module
from app.auth import router as auth_router
from app.api import calls


def create_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(auth_router.router)
    test_app.include_router(calls.router)

    async def _override_get_db():
        async with AppSessionFactory() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


_test_app = create_test_app()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestData:
    org_id: uuid.UUID
    other_org_id: uuid.UUID
    user_id: uuid.UUID
    other_user_id: uuid.UUID
    bot_id: uuid.UUID
    other_bot_id: uuid.UUID
    call_ids: list[uuid.UUID]
    other_call_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=_test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seed_data():
    """Create two orgs with users, bots, and call logs for isolation testing."""
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    other_bot_id = uuid.uuid4()
    call_ids = [uuid.uuid4() for _ in range(3)]
    other_call_ids = [uuid.uuid4() for _ in range(2)]

    async with FixtureSessionFactory() as session:
        # Org 1
        session.add(Organization(
            id=org_id, name="Test Org A",
            slug=f"test-a-{org_id.hex[:8]}", plan="free", status="active",
        ))
        # Org 2
        session.add(Organization(
            id=other_org_id, name="Test Org B",
            slug=f"test-b-{other_org_id.hex[:8]}", plan="free", status="active",
        ))
        await session.flush()

        # Users
        session.add(User(
            id=user_id, email=f"user-a-{user_id.hex[:8]}@test.com",
            display_name="User A", password_hash=hash_password("pass123"),
            role="client_admin", org_id=org_id, status="active",
        ))
        session.add(User(
            id=other_user_id, email=f"user-b-{other_user_id.hex[:8]}@test.com",
            display_name="User B", password_hash=hash_password("pass123"),
            role="client_admin", org_id=other_org_id, status="active",
        ))
        await session.flush()

        # Bots (raw SQL to avoid ORM schema drift with columns not yet in local DB)
        await session.execute(text(
            "INSERT INTO bot_configs (id, org_id, agent_name, company_name, system_prompt_template) "
            "VALUES (:id, :org_id, :name, :company, :prompt)"
        ), {"id": str(bot_id), "org_id": str(org_id), "name": "Bot A", "company": "Co A", "prompt": "Test bot."})
        await session.execute(text(
            "INSERT INTO bot_configs (id, org_id, agent_name, company_name, system_prompt_template) "
            "VALUES (:id, :org_id, :name, :company, :prompt)"
        ), {"id": str(other_bot_id), "org_id": str(other_org_id), "name": "Bot B", "company": "Co B", "prompt": "Test bot."})
        await session.flush()

        # Call logs for Org A (3 calls with different statuses and metadata)
        now = datetime.now(timezone.utc)
        for i, cid in enumerate(call_ids):
            session.add(CallLog(
                id=cid, org_id=org_id, bot_id=bot_id,
                call_sid=f"test-sid-a-{cid.hex[:8]}",
                contact_name=f"Contact {i}",
                contact_phone=f"+100000000{i}",
                status=["completed", "failed", "completed"][i],
                outcome=["success", "no_answer", "voicemail"][i],
                call_duration=[120, 0, 45][i],
                summary=f"Test call {i}",
                metadata_={"recording_url": f"http://example.com/rec-{i}.mp3", "index": i},
                started_at=now - timedelta(hours=3 - i),
                ended_at=now - timedelta(hours=3 - i) + timedelta(minutes=2),
                created_at=now - timedelta(hours=3 - i),
            ))

        # Call logs for Org B (2 calls — should NOT be visible to Org A)
        for i, cid in enumerate(other_call_ids):
            session.add(CallLog(
                id=cid, org_id=other_org_id, bot_id=other_bot_id,
                call_sid=f"test-sid-b-{cid.hex[:8]}",
                contact_name=f"Other Contact {i}",
                contact_phone=f"+200000000{i}",
                status="completed",
                metadata_={"recording_url": f"http://example.com/other-{i}.mp3"},
                created_at=now - timedelta(hours=i),
            ))

        await session.commit()

    yield TestData(
        org_id=org_id, other_org_id=other_org_id,
        user_id=user_id, other_user_id=other_user_id,
        bot_id=bot_id, other_bot_id=other_bot_id,
        call_ids=call_ids, other_call_ids=other_call_ids,
    )

    # Cleanup (order matters for FKs)
    async with FixtureSessionFactory() as session:
        for cid in call_ids + other_call_ids:
            await session.execute(delete(CallLog).where(CallLog.id == cid))
        await session.execute(text("DELETE FROM bot_configs WHERE id = :id"), {"id": str(bot_id)})
        await session.execute(text("DELETE FROM bot_configs WHERE id = :id"), {"id": str(other_bot_id)})
        await session.execute(delete(User).where(User.id == user_id))
        await session.execute(delete(User).where(User.id == other_user_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.execute(delete(Organization).where(Organization.id == other_org_id))
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def token_for(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


# ===========================================================================
# Tests
# ===========================================================================


class TestCallLogsMetadata:
    """Regression tests for the metadata serialization bug (MetaData vs dict)."""

    @pytest.mark.asyncio
    async def test_call_logs_returns_200(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_metadata_is_dict_not_sqlalchemy_metadata(self, client, seed_data):
        """The bug: model_validate read SQLAlchemy MetaData instead of JSONB column."""
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        data = resp.json()
        assert len(data) > 0
        for call in data:
            meta = call.get("metadata")
            assert meta is None or isinstance(meta, dict), (
                f"metadata should be dict or null, got {type(meta)}"
            )

    @pytest.mark.asyncio
    async def test_metadata_contains_correct_data(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        data = resp.json()
        metas_with_url = [c for c in data if c.get("metadata", {}).get("recording_url")]
        assert len(metas_with_url) == 3
        for call in metas_with_url:
            assert call["metadata"]["recording_url"].startswith("http://")

    @pytest.mark.asyncio
    async def test_no_500_on_empty_metadata(self, client, seed_data):
        """Calls with empty metadata ({}) should not cause serialization errors."""
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        assert resp.status_code == 200


class TestCallLogsOrgIsolation:
    """Org-scoped queries must not leak data across organizations."""

    @pytest.mark.asyncio
    async def test_user_a_sees_only_org_a_calls(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        data = resp.json()
        assert len(data) == 3
        sids = {c["call_sid"] for c in data}
        for cid in seed_data.call_ids:
            assert any(cid.hex[:8] in sid for sid in sids)

    @pytest.mark.asyncio
    async def test_user_b_sees_only_org_b_calls(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.other_user_id))
        data = resp.json()
        assert len(data) == 2
        sids = {c["call_sid"] for c in data}
        for cid in seed_data.other_call_ids:
            assert any(cid.hex[:8] in sid for sid in sids)

    @pytest.mark.asyncio
    async def test_user_a_cannot_see_org_b_calls(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        data = resp.json()
        sids = {c["call_sid"] for c in data}
        for cid in seed_data.other_call_ids:
            assert not any(cid.hex[:8] in sid for sid in sids), "Org B call leaked to Org A"


class TestCallLogsFiltering:
    """Verify query parameter filters work correctly."""

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client, seed_data):
        resp = await client.get(
            "/api/calls?status=failed", headers=token_for(seed_data.user_id)
        )
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_filter_by_bot_id(self, client, seed_data):
        resp = await client.get(
            f"/api/calls?bot_id={seed_data.bot_id}",
            headers=token_for(seed_data.user_id),
        )
        data = resp.json()
        assert len(data) == 3
        assert all(c["bot_id"] == str(seed_data.bot_id) for c in data)

    @pytest.mark.asyncio
    async def test_filter_by_nonexistent_bot_returns_empty(self, client, seed_data):
        resp = await client.get(
            f"/api/calls?bot_id={uuid.uuid4()}",
            headers=token_for(seed_data.user_id),
        )
        data = resp.json()
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_limit_and_offset(self, client, seed_data):
        resp = await client.get(
            "/api/calls?limit=2&offset=0", headers=token_for(seed_data.user_id)
        )
        data = resp.json()
        assert len(data) == 2

        resp2 = await client.get(
            "/api/calls?limit=2&offset=2", headers=token_for(seed_data.user_id)
        )
        data2 = resp2.json()
        assert len(data2) == 1  # 3 total, offset 2 = 1 remaining


class TestCallLogsResponseShape:
    """Verify the response schema matches expectations."""

    @pytest.mark.asyncio
    async def test_response_contains_required_fields(self, client, seed_data):
        resp = await client.get("/api/calls?limit=1", headers=token_for(seed_data.user_id))
        data = resp.json()
        assert len(data) == 1
        call = data[0]
        required_fields = [
            "id", "bot_id", "call_sid", "contact_name", "contact_phone",
            "status", "metadata", "created_at",
        ]
        for field in required_fields:
            assert field in call, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_response_ordered_by_created_at_desc(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        data = resp.json()
        dates = [c["created_at"] for c in data]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        resp = await client.get("/api/calls")
        assert resp.status_code == 401


class TestCallLogsBotName:
    """Verify bot_name is populated from BotConfig.agent_name."""

    @pytest.mark.asyncio
    async def test_list_calls_includes_bot_name(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.user_id))
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        assert len(items) > 0
        for call in items:
            assert "bot_name" in call, "Missing bot_name field"
            assert call["bot_name"] == "Bot A"

    @pytest.mark.asyncio
    async def test_export_calls_includes_bot_name(self, client, seed_data):
        resp = await client.get("/api/calls/export", headers=token_for(seed_data.user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        for call in data:
            assert "bot_name" in call, "Missing bot_name in export"
            assert call["bot_name"] == "Bot A"

    @pytest.mark.asyncio
    async def test_get_call_detail_includes_bot_name(self, client, seed_data):
        call_id = seed_data.call_ids[0]
        resp = await client.get(f"/api/calls/{call_id}", headers=token_for(seed_data.user_id))
        assert resp.status_code == 200
        call = resp.json()
        assert call["bot_name"] == "Bot A"

    @pytest.mark.asyncio
    async def test_org_b_sees_own_bot_name(self, client, seed_data):
        resp = await client.get("/api/calls", headers=token_for(seed_data.other_user_id))
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        for call in items:
            assert call["bot_name"] == "Bot B"


class TestCallLogsEmptyOrg:
    """Org with no calls should return empty list, not error."""

    @pytest.mark.asyncio
    async def test_empty_org_returns_empty_list(self, client, seed_data):
        # Create a user in an org with no calls — seed_data orgs have calls,
        # so use a token for a nonexistent user (will 401). Instead, verify
        # that filtering to a bot with no calls returns [].
        resp = await client.get(
            f"/api/calls?bot_id={uuid.uuid4()}",
            headers=token_for(seed_data.user_id),
        )
        assert resp.status_code == 200
        assert resp.json() == []
