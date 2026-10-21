from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import current_user, get_payments
from app.schemas.accounts import CardIn, CheckoutIn, PaymentOut
from app.security import TokenClaims
from app.services.payments import (
    PaymentAlreadyProcessedError,
    PaymentNotFoundError,
    PaymentService,
)

router = APIRouter(prefix="/payments", tags=["payments"])

Payments = Annotated[PaymentService, Depends(get_payments)]
User = Annotated[TokenClaims, Depends(current_user)]


@router.post("/checkout", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def checkout(body: CheckoutIn, claims: User, payments: Payments) -> PaymentOut:
    """Starts a wallet top-up (simulated card gateway). Pay it with /payments/{id}/confirm."""
    try:
        return await payments.checkout(claims.uid, body.amount)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.post("/{payment_id}/confirm", response_model=PaymentOut)
async def confirm(payment_id: str, card: CardIn, claims: User, payments: Payments) -> PaymentOut:
    """Pays the checkout with a card. A declined card answers 200 with status "failed" and
    a failure_reason, like a real gateway; the wallet is credited only on success."""
    try:
        return await payments.confirm(claims.uid, payment_id, card)
    except PaymentNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such payment") from e
    except PaymentAlreadyProcessedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "This payment was already processed") from e


@router.get("", response_model=list[PaymentOut])
async def list_payments(claims: User, payments: Payments) -> list[PaymentOut]:
    """The user's payments and receipts, newest first."""
    return await payments.history(claims.uid)
