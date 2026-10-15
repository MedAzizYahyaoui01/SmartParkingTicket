from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_parking
from app.schemas.reservations import ReservationIn, ReservationOut
from app.services.parking import (
    ParkingService,
    ReservationNotFoundError,
    SpotUnavailableError,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    parking: Annotated[ParkingService, Depends(get_parking)],
) -> list[ReservationOut]:
    """Active reservations, oldest first."""
    return parking.list_reservations()


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    body: ReservationIn, parking: Annotated[ParkingService, Depends(get_parking)]
) -> ReservationOut:
    """Holds a free spot for `duration_min` minutes (simulated booking).
    409 if the spot is occupied, already reserved, or its state is not known yet."""
    try:
        return await parking.create_reservation(body.spot_id, body.name, body.duration_min)
    except SpotUnavailableError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation(
    reservation_id: str, parking: Annotated[ParkingService, Depends(get_parking)]
) -> Response:
    try:
        await parking.cancel_reservation(reservation_id)
    except ReservationNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active reservation with this ID") from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
