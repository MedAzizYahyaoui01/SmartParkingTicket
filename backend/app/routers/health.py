from fastapi import APIRouter

from app import db
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness check used by Docker and CI.

    Always answers 200 while the API process is up; the "mongo" field reports
    whether the history database is reachable, without failing the check.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "mongo": "up" if await db.ping() else "down",
    }
