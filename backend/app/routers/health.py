from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_parking, get_settings_dep
from app.services.parking import ParkingService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    parking: Annotated[ParkingService, Depends(get_parking)],
) -> dict:
    """Liveness check used by Docker and CI.

    Always answers 200 while the API process is up; the "mongo" field reports
    whether the history database is reachable, without failing the check.
    """
    return {
        "status": "ok",
        "version": settings.app_version,
        "mongo": "up" if await parking.history.ping() else "down",
    }
