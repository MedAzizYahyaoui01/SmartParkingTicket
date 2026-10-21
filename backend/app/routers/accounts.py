from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import current_identity, current_user, get_accounts
from app.schemas.accounts import (
    AccessCodeOut,
    AuthOut,
    LoginIn,
    PricingOut,
    ProfileUpdateIn,
    RegisterIn,
    TransactionOut,
    UserOut,
)
from app.security import TokenClaims
from app.services.accounts import AccountService, EmailTakenError, InvalidCredentialsError

router = APIRouter(tags=["accounts"])

Accounts = Annotated[AccountService, Depends(get_accounts)]


async def _auth_out(accounts: AccountService, user: dict) -> AuthOut:
    token, expires_at = accounts.issue_token(user["_id"], "user")
    return AuthOut(token=token, expires_at=expires_at, user=await accounts.user_out(user))


@router.post("/auth/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, accounts: Accounts) -> AuthOut:
    """Creates an account (with its UID and an empty wallet) and signs it in."""
    try:
        user = await accounts.register(
            body.name, body.email, body.password, body.plate, body.language
        )
    except EmailTakenError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already uses this e-mail") from e
    return await _auth_out(accounts, user)


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, accounts: Accounts) -> AuthOut:
    try:
        user = await accounts.login(body.email, body.password)
    except InvalidCredentialsError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong e-mail or password") from e
    return await _auth_out(accounts, user)


@router.get("/pricing", response_model=PricingOut)
async def pricing(accounts: Accounts) -> PricingOut:
    """Public prices and gate rules (amounts in millimes)."""
    return accounts.pricing()


@router.get("/me", response_model=UserOut)
async def me(
    claims: Annotated[TokenClaims, Depends(current_identity)], accounts: Accounts
) -> UserOut:
    """Profile, wallet balance and status, current stay and reservation."""
    return await accounts.user_out(await accounts.get_user(claims.uid))


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: ProfileUpdateIn,
    claims: Annotated[TokenClaims, Depends(current_user)],
    accounts: Accounts,
) -> UserOut:
    user = await accounts.update_profile(claims.uid, body.model_dump())
    return await accounts.user_out(user)


@router.get("/me/transactions", response_model=list[TransactionOut])
async def my_transactions(
    claims: Annotated[TokenClaims, Depends(current_identity)],
    accounts: Accounts,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TransactionOut]:
    """Wallet statement, newest first."""
    return await accounts.transactions(claims.uid, limit)


@router.post("/me/access-code", response_model=AccessCodeOut)
async def access_code(
    claims: Annotated[TokenClaims, Depends(current_user)], accounts: Accounts
) -> AccessCodeOut:
    """A short-lived code to show at the gate kiosk, as a QR code or as 6 digits."""
    return accounts.new_access_code(claims.uid)
