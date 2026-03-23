"""Tests for auth/dependencies.py — ROLE_HIERARCHY and require_role logic."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.auth.dependencies import ROLE_HIERARCHY


# ---------------------------------------------------------------------------
# ROLE_HIERARCHY
# ---------------------------------------------------------------------------

class TestRoleHierarchy:
    def test_client_user_is_lowest(self):
        assert ROLE_HIERARCHY["client_user"] == 0

    def test_client_admin_above_client_user(self):
        assert ROLE_HIERARCHY["client_admin"] > ROLE_HIERARCHY["client_user"]

    def test_super_admin_is_highest(self):
        assert ROLE_HIERARCHY["super_admin"] > ROLE_HIERARCHY["client_admin"]
        assert ROLE_HIERARCHY["super_admin"] > ROLE_HIERARCHY["client_user"]

    def test_all_roles_present(self):
        assert set(ROLE_HIERARCHY.keys()) == {"client_user", "client_admin", "super_admin"}

    def test_hierarchy_values_unique(self):
        values = list(ROLE_HIERARCHY.values())
        assert len(values) == len(set(values))

    def test_hierarchy_values_sorted(self):
        roles_by_level = sorted(ROLE_HIERARCHY.items(), key=lambda x: x[1])
        assert [r[0] for r in roles_by_level] == ["client_user", "client_admin", "super_admin"]


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_token_active_user(self):
        user = SimpleNamespace(id="user-1", role="client_admin", status="active", org_id="org-1")
        mock_result = SimpleNamespace(scalar_one_or_none=lambda: user)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "00000000-0000-0000-0000-000000000001", "type": "access"}
            from app.auth.dependencies import get_current_user
            result = await get_current_user(token="valid-token", db=mock_db)
            assert result is user

    @pytest.mark.asyncio
    async def test_jwt_error_raises_401(self):
        from jose import JWTError
        mock_db = AsyncMock()

        with patch("app.auth.dependencies.decode_token", side_effect=JWTError("bad")):
            from app.auth.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="bad-token", db=mock_db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_sub_raises_401(self):
        mock_db = AsyncMock()

        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.return_value = {"type": "access"}  # no "sub"
            from app.auth.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="token", db=mock_db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_type_raises_401(self):
        mock_db = AsyncMock()

        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "00000000-0000-0000-0000-000000000001", "type": "refresh"}
            from app.auth.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="token", db=mock_db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        mock_result = SimpleNamespace(scalar_one_or_none=lambda: None)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "00000000-0000-0000-0000-000000000001", "type": "access"}
            from app.auth.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="token", db=mock_db)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_raises_403(self):
        user = SimpleNamespace(id="user-1", role="client_admin", status="suspended", org_id="org-1")
        mock_result = SimpleNamespace(scalar_one_or_none=lambda: user)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.auth.dependencies.decode_token") as mock_decode:
            mock_decode.return_value = {"sub": "00000000-0000-0000-0000-000000000001", "type": "access"}
            from app.auth.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="token", db=mock_db)
            assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------

class TestRequireRole:
    @pytest.mark.asyncio
    async def test_user_has_required_role(self):
        user = SimpleNamespace(id="user-1", role="client_admin", status="active", org_id="org-1")
        from app.auth.dependencies import require_role
        checker = require_role("client_admin", "super_admin")
        result = await checker(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_user_lacks_required_role(self):
        user = SimpleNamespace(id="user-1", role="client_user", status="active", org_id="org-1")
        from app.auth.dependencies import require_role
        checker = require_role("client_admin", "super_admin")
        with pytest.raises(HTTPException) as exc_info:
            await checker(user=user)
        assert exc_info.value.status_code == 403
