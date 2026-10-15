"""Objects the routes need, taken from the running app (so tests can swap them)."""

import secrets

from fastapi import Header, HTTPException, Request, status

from app.config import Settings
from app.services.parking import ParkingService
from app.services.stats import StatsService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_parking(request: Request) -> ParkingService:
    return request.app.state.parking


def get_stats(request: Request) -> StatsService:
    return request.app.state.stats


async def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """The ESP32 must send the shared secret in the X-API-Key header."""
    expected = request.app.state.settings.api_key
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key"
        )
