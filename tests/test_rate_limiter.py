# tests/test_rate_limiter.py
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_can_contact_allows_first_contact():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # No prior contacts
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result

    limiter = RateLimiter(db=mock_db)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is True


@pytest.mark.asyncio
async def test_can_contact_blocks_when_daily_cap_reached():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # 5 contacts today (at daily cap)
    mock_result = MagicMock()
    mock_result.scalar.return_value = 5
    mock_db.execute.return_value = mock_result

    limiter = RateLimiter(db=mock_db, daily_cap=5)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_can_contact_blocks_when_hourly_cap_reached():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # Simulate: daily OK (3), hourly at cap (2)
    mock_result_daily = MagicMock()
    mock_result_daily.scalar.return_value = 3
    mock_result_hourly = MagicMock()
    mock_result_hourly.scalar.return_value = 2
    mock_db.execute.side_effect = [mock_result_daily, mock_result_hourly]

    limiter = RateLimiter(db=mock_db, daily_cap=5, hourly_cap=2)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_can_contact_blocks_during_cooldown():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    # Daily OK (1), hourly OK (1), but last contact was 30s ago (within 60s cooldown)
    mock_result_daily = MagicMock()
    mock_result_daily.scalar.return_value = 1
    mock_result_hourly = MagicMock()
    mock_result_hourly.scalar.return_value = 1
    mock_result_last = MagicMock()
    mock_result_last.scalar.return_value = datetime.utcnow() - timedelta(seconds=30)
    mock_db.execute.side_effect = [mock_result_daily, mock_result_hourly, mock_result_last]

    limiter = RateLimiter(db=mock_db, daily_cap=5, hourly_cap=2, cooldown_seconds=60)
    result = await limiter.can_contact(lead_id="lead-1", org_id="org-1")
    assert result is False


@pytest.mark.asyncio
async def test_record_contact_inserts_row():
    from app.services.rate_limiter import RateLimiter
    mock_db = AsyncMock()
    limiter = RateLimiter(db=mock_db)

    await limiter.record_contact(lead_id="lead-1", org_id="org-1", channel="whatsapp_template")
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
