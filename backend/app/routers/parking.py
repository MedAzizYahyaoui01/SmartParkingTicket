from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies import get_parking
from app.schemas.parking import BarrierCommandIn, BarrierCommandOut, ParkingOut
from app.services.parking import ParkingService

router = APIRouter(tags=["parking"])


@router.get("/spots", response_model=ParkingOut)
async def get_spots(parking: Annotated[ParkingService, Depends(get_parking)]) -> ParkingOut:
    """Current state of every spot, the device and the barrier."""
    return parking.get_state()


@router.post(
    "/barrier/command", response_model=BarrierCommandOut, status_code=status.HTTP_202_ACCEPTED
)
async def post_barrier_command(
    body: BarrierCommandIn, parking: Annotated[ParkingService, Depends(get_parking)]
) -> BarrierCommandOut:
    """Manual open/close from the dashboard. Accepted now, delivered to the ESP32 in its
    next response (status goes from "pending" to "delivered" in Firebase)."""
    return await parking.submit_barrier_command(body.action)
