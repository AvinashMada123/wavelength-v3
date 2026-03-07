"""
Concurrent session limiter.

Prevents resource exhaustion by capping the number of active voice pipelines.
Usage:
    if not await session_limiter.acquire():
        raise HTTPException(429, "At capacity")
    try:
        await run_pipeline(...)
    finally:
        await session_limiter.release()
"""

from __future__ import annotations

import asyncio
import os

import structlog

logger = structlog.get_logger(__name__)

MAX_CONCURRENT_SESSIONS = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "50"))

_active = 0
_lock = asyncio.Lock()


async def acquire() -> bool:
    """Try to acquire a session slot. Returns False if at capacity."""
    global _active
    async with _lock:
        if _active >= MAX_CONCURRENT_SESSIONS:
            logger.warning("session_limit_reached", active=_active, max=MAX_CONCURRENT_SESSIONS)
            return False
        _active += 1
        logger.info("session_acquired", active=_active, max=MAX_CONCURRENT_SESSIONS)
        return True


async def release():
    """Release a session slot."""
    global _active
    async with _lock:
        _active = max(0, _active - 1)
        logger.info("session_released", active=_active)


def active_count() -> int:
    return _active
