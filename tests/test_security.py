"""Tests for app.auth.security — JWT tokens and password hashing."""

from __future__ import annotations

import sys
from datetime import timedelta, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

# Mock structlog before importing app modules
sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Mock settings so tests don't need .env
_mock_settings = SimpleNamespace(
    JWT_SECRET="test-secret-key-for-unit-tests-only",
    JWT_ALGORITHM="HS256",
)

with patch("app.config.settings", _mock_settings):
    from app.auth.security import (
        hash_password,
        verify_password,
        create_access_token,
        create_refresh_token,
        decode_token,
        ACCESS_TOKEN_EXPIRE,
        REFRESH_TOKEN_EXPIRE,
    )


# ---------------------------------------------------------------------------
# hash_password / verify_password
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        hashed = hash_password("my-secret-password")
        assert verify_password("my-secret-password", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self):
        hashed = hash_password("plaintext")
        assert hashed != "plaintext"
        assert hashed.startswith("$2")  # bcrypt prefix

    def test_different_hashes_for_same_password(self):
        """bcrypt uses random salt, so two hashes of the same password differ."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        # Both should still verify
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False

    def test_unicode_password(self):
        hashed = hash_password("pässwörd-日本語")
        assert verify_password("pässwörd-日本語", hashed) is True

    def test_long_password_raises(self):
        """bcrypt 5.x rejects passwords > 72 bytes."""
        import pytest

        long_pw = "a" * 200
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password(long_pw)


# ---------------------------------------------------------------------------
# create_access_token / create_refresh_token / decode_token
# ---------------------------------------------------------------------------

class TestAccessToken:
    def test_create_and_decode(self):
        token = create_access_token({"sub": "user-123"})
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_custom_expiry(self):
        token = create_access_token(
            {"sub": "u1"}, expires_delta=timedelta(minutes=5)
        )
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        # Should expire within ~5 minutes (allow 10s tolerance)
        assert timedelta(minutes=4, seconds=50) < (exp - now) < timedelta(minutes=5, seconds=10)

    def test_default_expiry_is_24h(self):
        token = create_access_token({"sub": "u1"})
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = exp - now
        assert timedelta(hours=23, minutes=59) < diff < timedelta(hours=24, seconds=10)

    def test_preserves_extra_claims(self):
        token = create_access_token({"sub": "u1", "org_id": "org-42", "role": "admin"})
        payload = decode_token(token)
        assert payload["org_id"] == "org-42"
        assert payload["role"] == "admin"

    def test_does_not_mutate_input(self):
        data = {"sub": "u1"}
        create_access_token(data)
        assert "exp" not in data
        assert "type" not in data


class TestRefreshToken:
    def test_create_and_decode(self):
        token = create_refresh_token({"sub": "user-456"})
        payload = decode_token(token)
        assert payload["sub"] == "user-456"
        assert payload["type"] == "refresh"

    def test_refresh_expiry_is_30d(self):
        token = create_refresh_token({"sub": "u1"})
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = exp - now
        assert timedelta(days=29, hours=23) < diff < timedelta(days=30, seconds=10)

    def test_does_not_mutate_input(self):
        data = {"sub": "u1"}
        create_refresh_token(data)
        assert "exp" not in data


class TestDecodeToken:
    @pytest.mark.parametrize(
        "token_factory,description",
        [
            pytest.param(lambda: "not-a-valid-jwt", "invalid token", id="invalid_token"),
            pytest.param(
                lambda: __import__("jose").jwt.encode(
                    {"sub": "u1", "type": "access"}, "different-secret", algorithm="HS256"
                ),
                "wrong secret",
                id="wrong_secret",
            ),
            pytest.param(
                lambda: create_access_token({"sub": "u1"}, expires_delta=timedelta(seconds=-1)),
                "expired token",
                id="expired_token",
            ),
            pytest.param(lambda: "", "empty string", id="empty_string"),
        ],
    )
    def test_decode_error_raises(self, token_factory, description):
        from jose import JWTError

        with pytest.raises(JWTError):
            decode_token(token_factory())
