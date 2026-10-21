from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import current_identity, get_accounts, get_gate
from app.schemas.accounts import GateDecisionOut, IdentifyIn, KioskSessionOut
from app.security import TokenClaims
from app.services.accounts import (
    AccountService,
    InvalidAccessCodeError,
    TooManyAttemptsError,
)
from app.services.gate import GateService

router = APIRouter(prefix="/gate", tags=["gate"])

Gate = Annotated[GateService, Depends(get_gate)]
Identity = Annotated[TokenClaims, Depends(current_identity)]


@router.post("/identify", response_model=KioskSessionOut)
async def identify(
    body: IdentifyIn,
    request: Request,
    accounts: Annotated[AccountService, Depends(get_accounts)],
) -> KioskSessionOut:
    """The kiosk scanned (or the driver typed) the code from the app: opens a short kiosk
    session for that account."""
    client = request.client.host if request.client else "unknown"
    try:
        uid = accounts.redeem_access_code(body.code, client)
    except TooManyAttemptsError as e:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong codes, wait a minute"
        ) from e
    except InvalidAccessCodeError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or expired code") from e
    token, expires_at = accounts.issue_token(uid, "kiosk")
    user = await accounts.user_out(await accounts.get_user(uid))
    return KioskSessionOut(token=token, expires_at=expires_at, user=user)


@router.post("/enter", response_model=GateDecisionOut)
async def enter(claims: Identity, gate: Gate) -> GateDecisionOut:
    """Opens the barrier for the user if they may enter (see `reason` when refused)."""
    return await gate.enter(claims.uid)


@router.post("/exit", response_model=GateDecisionOut)
async def exit_(claims: Identity, gate: Gate) -> GateDecisionOut:
    """Charges the stay to the wallet and opens the barrier."""
    return await gate.exit(claims.uid)
