"""
FastAPI application entry point.

Lifespan manages:
- AsyncPG connection pool (for BotConfigLoader)
- GHLClient session
- Dependency injection into route modules
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI

# Load .env into os.environ so Google Cloud libraries can find GOOGLE_APPLICATION_CREDENTIALS.
# pydantic-settings only loads its own fields, not arbitrary env vars.
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value

from app.api import analytics, bots, calls, health, queue, webhook
from app.bot_config.loader import BotConfigLoader
from app.database import close_asyncpg_pool, init_asyncpg_pool
from app.ghl.client import GHLClient
from app.plivo import routes as plivo_routes
from app.services import queue_processor
from app.twilio import routes as twilio_routes

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # --- Startup ---
    logger.info("app_starting")

    # Init asyncpg pool for BotConfigLoader
    pool = await init_asyncpg_pool()
    bot_config_loader = BotConfigLoader(db_pool=pool)

    # Init GHL client
    ghl_client = GHLClient()

    # Inject dependencies into route modules
    calls.set_dependencies(loader=bot_config_loader)
    bots.set_dependencies(loader=bot_config_loader)
    webhook.set_dependencies(loader=bot_config_loader)
    plivo_routes.set_dependencies(loader=bot_config_loader, ghl=ghl_client)
    twilio_routes.set_dependencies(loader=bot_config_loader, ghl=ghl_client)

    # Start background queue processor
    queue_processor.start(bot_config_loader)

    logger.info("app_started")

    yield

    # --- Shutdown ---
    logger.info("app_shutting_down")
    await queue_processor.stop()
    await ghl_client.close()
    await close_asyncpg_pool()
    logger.info("app_shutdown_complete")


app = FastAPI(
    title="Wavelength Voice Agent",
    description="Multi-tenant outbound AI voice calling system",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount routers
app.include_router(health.router)
app.include_router(calls.router)
app.include_router(bots.router)
app.include_router(webhook.router)
app.include_router(queue.router)
app.include_router(analytics.router)
app.include_router(plivo_routes.router)
app.include_router(twilio_routes.router)
