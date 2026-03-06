"""Health check endpoint for Cloud Run."""

from fastapi import APIRouter
from sqlalchemy import text

from app.database import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Cloud Run health check — verifies app is running and DB is reachable."""
    db_ok = False
    try:
        async with get_db_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
    }
