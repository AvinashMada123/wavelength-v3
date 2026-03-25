from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import asyncpg
import structlog

from app.models.bot_config import BotConfig

logger = structlog.get_logger(__name__)

_BOT_CONFIG_UPDATES_CHANNEL = "bot_config_updates"


class BotConfigLoader:
    """Loads bot configs from Postgres with an in-memory TTL cache."""

    def __init__(self, db_pool: asyncpg.Pool, cache_ttl: int = 300):
        self._db_pool = db_pool
        self._cache: dict[str, tuple[BotConfig, float]] = {}
        self._cache_ttl = cache_ttl
        self._listener_conn: asyncpg.Connection | None = None
        self._listener_lock = asyncio.Lock()

    async def start(self):
        """Start listening for cross-worker bot-config invalidation events."""
        async with self._listener_lock:
            if self._listener_conn is not None:
                return

            for attempt in range(3):
                try:
                    conn = await self._db_pool.acquire()
                    await conn.add_listener(
                        _BOT_CONFIG_UPDATES_CHANNEL,
                        self._handle_invalidation_notification,
                    )
                    self._listener_conn = conn
                    logger.info("bot_config_loader_listener_started", channel=_BOT_CONFIG_UPDATES_CHANNEL)
                    return
                except Exception:
                    logger.warning(
                        "bot_config_loader_listener_start_failed",
                        attempt=attempt + 1,
                        exc_info=True,
                    )
                    if attempt < 2:
                        await asyncio.sleep(1)

            logger.error("bot_config_loader_listener_start_gave_up")

    async def stop(self):
        """Stop listening for invalidation events and release the dedicated connection."""
        async with self._listener_lock:
            if self._listener_conn is None:
                return

            conn = self._listener_conn
            self._listener_conn = None
            try:
                await asyncio.wait_for(
                    conn.remove_listener(
                        _BOT_CONFIG_UPDATES_CHANNEL,
                        self._handle_invalidation_notification,
                    ),
                    timeout=3.0,
                )
            except Exception:
                logger.warning("bot_config_loader_listener_cleanup_failed", exc_info=True)
            try:
                await self._db_pool.release(conn)
            except Exception:
                pass
            logger.info("bot_config_loader_listener_stopped", channel=_BOT_CONFIG_UPDATES_CHANNEL)

    async def get(self, bot_id: str | uuid.UUID) -> BotConfig | None:
        bot_id_str = str(bot_id)
        now = time.time()

        if bot_id_str in self._cache:
            config, cached_at = self._cache[bot_id_str]
            if now - cached_at < self._cache_ttl:
                return config

        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bot_configs WHERE id = $1 AND is_active = true",
                uuid.UUID(bot_id_str),
            )

        if not row:
            logger.warning("bot_config_not_found", bot_id=bot_id_str)
            return None

        config = _row_to_bot_config(dict(row))
        self._cache[bot_id_str] = (config, now)
        return config

    def invalidate(self, bot_id: str | uuid.UUID):
        self._cache.pop(str(bot_id), None)

    def invalidate_all(self):
        self._cache.clear()

    async def publish_invalidation(self, bot_id: str | uuid.UUID):
        """Broadcast a bot-config cache invalidation to all workers."""
        payload = str(bot_id)
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                "SELECT pg_notify($1, $2)",
                _BOT_CONFIG_UPDATES_CHANNEL,
                payload,
            )
        logger.info("bot_config_invalidation_published", bot_id=payload)

    def _handle_invalidation_notification(self, connection, pid, channel, payload):
        if payload == "*":
            self.invalidate_all()
            logger.info("bot_config_cache_invalidated_all", channel=channel, source_pid=pid)
            return

        self.invalidate(payload)
        logger.info("bot_config_cache_invalidated", bot_id=payload, channel=channel, source_pid=pid)


def _row_to_bot_config(row: dict[str, Any]) -> BotConfig:
    """Map an asyncpg row dict to a BotConfig ORM instance (detached)."""
    config = BotConfig()
    for key, value in row.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def fill_prompt_template(template: str, **kwargs: str) -> str:
    """
    Fill {placeholder} variables in a system prompt template.
    Unknown placeholders are left unchanged.
    """

    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return f"{{{key}}}"

    return template.format_map(SafeDict(**kwargs))
