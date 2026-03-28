"""Tests for _send_webhook in app/services/n8n_webhook.py."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault(
    "structlog",
    SimpleNamespace(
        get_logger=lambda *a, **kw: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
    ),
)

import asyncio

import pytest

from app.services.n8n_webhook import _send_webhook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL = "https://hook.example.com/test"
PAYLOAD = {"event": "post_call", "call_sid": "sid-1"}
AUTO_ID = "auto-test-1"


def _mock_response(status: int = 200, body: str = "OK"):
    """Create a mock aiohttp response with async context manager support."""
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=body)
    # Support async context manager (async with session.post(...) as resp)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _mock_session(*responses):
    """Build a mock aiohttp.ClientSession that yields responses in sequence.

    Each call to session.post() returns the next response in the list.
    """
    session = AsyncMock()
    post_mock = MagicMock()
    post_mock.side_effect = list(responses)
    session.post = post_mock
    # session itself is an async context manager
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


PATCH_SESSION = "app.services.n8n_webhook.aiohttp.ClientSession"
PATCH_SLEEP = "app.services.n8n_webhook.asyncio.sleep"


# ---------------------------------------------------------------------------
# TestRetryBehavior
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    """Verify retry logic on various HTTP status codes."""

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        session = _mock_session(_mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_500_then_succeed(self):
        session = _mock_session(_mock_response(500, "err"), _mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True
        assert session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_502(self):
        session = _mock_session(_mock_response(502, "bad gw"), _mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_retry_on_503(self):
        session = _mock_session(_mock_response(503, "unavail"), _mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_retry_on_504(self):
        session = _mock_session(_mock_response(504, "timeout"), _mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_returns_false(self):
        session = _mock_session(
            _mock_response(500, "err"),
            _mock_response(500, "err"),
            _mock_response(500, "err"),
        )
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID, max_retries=2)
        assert result is False
        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_backoff_timing(self):
        session = _mock_session(
            _mock_response(500, "err"),
            _mock_response(500, "err"),
            _mock_response(500, "err"),
        )
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock) as sleep_mock:
            await _send_webhook(URL, PAYLOAD, AUTO_ID, max_retries=2)
        # Backoff: sleep(1*1)=1s after attempt 0, sleep(1*2)=2s after attempt 1
        assert sleep_mock.await_count == 2
        sleep_mock.assert_any_await(1.0)
        sleep_mock.assert_any_await(2.0)

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        session = _mock_session(_mock_response(400, "bad request"))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock) as sleep_mock:
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is False
        assert session.post.call_count == 1
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_retry_on_401(self):
        session = _mock_session(_mock_response(401, "unauthorized"))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock) as sleep_mock:
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is False
        assert session.post.call_count == 1
        sleep_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestTimeoutHandling
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    """Verify timeout triggers retry behavior."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self):
        import aiohttp

        good_resp = _mock_response(200)
        session = AsyncMock()
        call_count = 0

        def post_side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError("request timed out")
            return good_resp

        session.post = MagicMock(side_effect=post_side_effect)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_timeouts_returns_false(self):
        session = AsyncMock()
        session.post = MagicMock(side_effect=asyncio.TimeoutError("timeout"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID, max_retries=2)
        assert result is False
        assert session.post.call_count == 3


# ---------------------------------------------------------------------------
# TestNetworkErrors
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    """Verify network/connection errors trigger retries."""

    @pytest.mark.asyncio
    async def test_connection_error_retry(self):
        import aiohttp

        good_resp = _mock_response(200)
        session = AsyncMock()
        call_count = 0

        def post_side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientConnectorError(
                    connection_key=MagicMock(), os_error=OSError("conn refused")
                )
            return good_resp

        session.post = MagicMock(side_effect=post_side_effect)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_general_exception_retry(self):
        good_resp = _mock_response(200)
        session = AsyncMock()
        call_count = 0

        def post_side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("something unexpected")
            return good_resp

        session.post = MagicMock(side_effect=post_side_effect)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_network_error_exhausts_retries(self):
        session = AsyncMock()
        session.post = MagicMock(side_effect=ConnectionError("no route"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID, max_retries=2)
        assert result is False
        assert session.post.call_count == 3


# ---------------------------------------------------------------------------
# TestNon200Responses
# ---------------------------------------------------------------------------


class TestNon200Responses:
    """Non-200 but < 400 status codes should be treated as success."""

    @pytest.mark.asyncio
    async def test_201_success(self):
        session = _mock_session(_mock_response(201))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_204_success(self):
        session = _mock_session(_mock_response(204))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_429_triggers_retry(self):
        session = _mock_session(_mock_response(429, "rate limited"), _mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, PAYLOAD, AUTO_ID)
        assert result is True
        assert session.post.call_count == 2


# ---------------------------------------------------------------------------
# TestPayloadSerialization
# ---------------------------------------------------------------------------


class TestPayloadSerialization:
    """Verify _json_serialize handles special types in payload."""

    @pytest.mark.asyncio
    async def test_datetime_values(self):
        payload = {"event": "test", "ts": datetime(2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc)}
        session = _mock_session(_mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, payload, AUTO_ID)
        assert result is True
        # Verify the serialized data was sent (contains ISO format string)
        call_kw = session.post.call_args
        sent_data = call_kw.kwargs.get("data") or call_kw[1].get("data")
        assert "2026-03-28T12:00:00" in sent_data

    @pytest.mark.asyncio
    async def test_uuid_values(self):
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        payload = {"event": "test", "id": test_uuid}
        session = _mock_session(_mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, payload, AUTO_ID)
        assert result is True
        call_kw = session.post.call_args
        sent_data = call_kw.kwargs.get("data") or call_kw[1].get("data")
        assert "12345678-1234-5678-1234-567812345678" in sent_data

    @pytest.mark.asyncio
    async def test_large_payload(self):
        payload = {"event": "test", "data": "x" * 100_000}
        session = _mock_session(_mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, payload, AUTO_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_payload(self):
        session = _mock_session(_mock_response(200))
        with patch(PATCH_SESSION, return_value=session), \
             patch(PATCH_SLEEP, new_callable=AsyncMock):
            result = await _send_webhook(URL, {}, AUTO_ID)
        assert result is True
        call_kw = session.post.call_args
        sent_data = call_kw.kwargs.get("data") or call_kw[1].get("data")
        assert sent_data == "{}"
