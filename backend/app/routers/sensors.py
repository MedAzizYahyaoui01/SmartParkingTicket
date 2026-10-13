from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_parking, require_api_key
from app.schemas.sensors import SensorReading, SensorResponse
from app.services.parking import ParkingService

router = APIRouter(prefix="/sensors", tags=["sensors"])


@router.post("/reading", response_model=SensorResponse, dependencies=[Depends(require_api_key)])
async def post_reading(
    reading: SensorReading, parking: Annotated[ParkingService, Depends(get_parking)]
) -> SensorResponse:
    """Called by the ESP32 on every change and every heartbeat.
    Returns the barrier command the ESP32 must apply."""
    return await parking.handle_reading(reading)
