from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import current_identity, get_accounts, get_parking
from app.schemas.accounts import AccountReservationIn
from app.schemas.reservations import ReservationOut
from app.security import TokenClaims
from app.services.accounts import (
    AccountBlockedError,
    AccountService,
    AlreadyReservedError,
    InsufficientFundsError,
)
from app.services.parking import (
    ParkingService,
    ReservationNotFoundError,
    SpotUnavailableError,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])

Accounts = Annotated[AccountService, Depends(get_accounts)]
Identity = Annotated[TokenClaims, Depends(current_identity)]


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    parking: Annotated[ParkingService, Depends(get_parking)],
) -> list[ReservationOut]:
    """Active reservations, oldest first."""
    return parking.list_reservations()


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    body: AccountReservationIn, claims: Identity, accounts: Accounts
) -> ReservationOut:
    """Holds a free spot for `duration_min` minutes for the signed-in user; the reservation
    fee is paid from their wallet. 402 if the credit is too low, 403 if the account owes
    money, 409 if the spot is taken or the user already has a reservation."""
    try:
        return await accounts.reserve(claims.uid, body.spot_id, body.duration_min)
    except InsufficientFundsError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "Not enough credit, please top up"
        ) from e
    except AccountBlockedError as e:
        detail = {
            "debt": "Your balance is negative, please top up first",
            "already_inside": "You are already parked inside",
        }.get(e.reason, e.reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail) from e
    except AlreadyReservedError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have an active reservation"
        ) from e
    except SpotUnavailableError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation(reservation_id: str, claims: Identity, accounts: Accounts) -> Response:
    """Cancels one of the user's own reservations and refunds the fee."""
    try:
        await accounts.cancel_reservation(claims.uid, reservation_id)
    except ReservationNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active reservation with this ID") from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
