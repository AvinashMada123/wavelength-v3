from __future__ import annotations

import time
import uuid
from typing import Any

import asyncpg
import structlog

from app.models.bot_config import BotConfig

logger = structlog.get_logger(__name__)


class BotConfigLoader:
    """Loads bot configs from Postgres with an in-memory TTL cache."""

    def __init__(self, db_pool: asyncpg.Pool, cache_ttl: int = 300):
        self._db_pool = db_pool
        self._cache: dict[str, tuple[BotConfig, float]] = {}
        self._cache_ttl = cache_ttl

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
