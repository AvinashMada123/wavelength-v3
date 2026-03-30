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

from app.api import admin, analytics, billing, bots, calls, campaigns, dnc, flow_migration, flows, health, leads, messaging_providers, payments, queue, sequence_analytics, sequences, telephony, webhook, webhooks
from app.auth import router as auth_router
from app.bot_config.loader import BotConfigLoader
from app.database import close_asyncpg_pool, init_asyncpg_pool
from app.ghl.client import GHLClient
from app.plivo import routes as plivo_routes
from app.services import queue_processor
from app.services import sequence_scheduler
from app.twilio import routes as twilio_routes

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # --- Startup ---
    logger.info("app_starting")

    # Security check: refuse to start with the default JWT secret
    from app.config import settings as _settings
    if _settings.JWT_SECRET == "CHANGE-ME-IN-PRODUCTION":
        if os.environ.get("TESTING") != "1":
            raise RuntimeError(
                "FATAL: JWT_SECRET is set to the default value. "
                "Set a strong, unique JWT_SECRET in your .env file before running in production."
            )

    # Init asyncpg pool for BotConfigLoader
    pool = await init_asyncpg_pool()
    bot_config_loader = BotConfigLoader(db_pool=pool)
    await bot_config_loader.start()

    # Init GHL client
    ghl_client = GHLClient()

    # Inject dependencies into route modules
    calls.set_dependencies(loader=bot_config_loader)
    bots.set_dependencies(loader=bot_config_loader)
    webhook.set_dependencies(loader=bot_config_loader)
    plivo_routes.set_dependencies(loader=bot_config_loader, ghl=ghl_client)
    twilio_routes.set_dependencies(loader=bot_config_loader, ghl=ghl_client)

    # Load ambient sound presets (singleton buffers shared across calls)
    if _settings.AMBIENT_SOUND_ENABLED:
        from app.audio.ambient import load_presets

        load_presets(_settings.AMBIENT_PRESETS_DIR or None)

    # Start background queue processor
    queue_processor.start(bot_config_loader)
    sequence_scheduler.start()

    logger.info("app_started")

    yield

    # --- Shutdown ---
    logger.info("app_shutting_down")
    await sequence_scheduler.stop()
    await queue_processor.stop()
    await bot_config_loader.stop()
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
app.include_router(auth_router.router)
app.include_router(calls.router)
app.include_router(bots.router)
app.include_router(webhook.router)
app.include_router(queue.router)
app.include_router(analytics.router)
app.include_router(leads.router)
app.include_router(dnc.router)
app.include_router(campaigns.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(payments.router)
app.include_router(telephony.router)
app.include_router(sequences.router)
app.include_router(sequence_analytics.router)
app.include_router(flows.router)
app.include_router(flow_migration.router)
app.include_router(messaging_providers.router)
app.include_router(webhooks.router)
app.include_router(plivo_routes.router)
app.include_router(twilio_routes.router)
