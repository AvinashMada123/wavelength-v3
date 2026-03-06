from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=False,
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Raw asyncpg pool for BotConfigLoader (lightweight queries outside ORM)
_asyncpg_pool: asyncpg.Pool | None = None


async def init_asyncpg_pool() -> asyncpg.Pool:
    global _asyncpg_pool
    if _asyncpg_pool is None:
        # Convert SQLAlchemy URL to raw asyncpg DSN
        dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        _asyncpg_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=settings.DATABASE_POOL_SIZE)
    return _asyncpg_pool


async def close_asyncpg_pool():
    global _asyncpg_pool
    if _asyncpg_pool:
        await _asyncpg_pool.close()
        _asyncpg_pool = None


async def get_db():
    """FastAPI dependency for SQLAlchemy async sessions."""
    async with async_session_factory() as session:
        yield session


@asynccontextmanager
async def get_db_session():
    """Context manager for use outside of FastAPI request handlers."""
    async with async_session_factory() as session:
        yield session
