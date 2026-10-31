"""Objects the routes need, taken from the running app (so tests can swap them)."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.security import InvalidTokenError, TokenClaims, decode_token
from app.services.accounts import AccountService
from app.services.assistant.service import AssistantService
from app.services.gate import GateService
from app.services.parking import ParkingService
from app.services.payments import PaymentService
from app.services.predictions import PredictionService
from app.services.stats import StatsService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_parking(request: Request) -> ParkingService:
    return request.app.state.parking


def get_stats(request: Request) -> StatsService:
    return request.app.state.stats


def get_predictions(request: Request) -> PredictionService:
    return request.app.state.predictions


async def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """The ESP32 must send the shared secret in the X-API-Key header."""
    expected = request.app.state.settings.api_key
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key"
        )


def get_accounts(request: Request) -> AccountService:
    return request.app.state.accounts


def get_gate(request: Request) -> GateService:
    return request.app.state.gate


def get_payments(request: Request) -> PaymentService:
    return request.app.state.payments


def get_assistant(request: Request) -> AssistantService:
    return request.app.state.assistant


_bearer = HTTPBearer(auto_error=False)


def _claims(request: Request, credentials: HTTPAuthorizationCredentials | None) -> TokenClaims:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign-in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials, request.app.state.settings.jwt_secret)
    except InvalidTokenError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired session, please sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def current_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    """The signed-in user, from the app (scope "user") or the gate kiosk (scope "kiosk")."""
    return _claims(request, credentials)


async def current_user(
    claims: Annotated[TokenClaims, Depends(current_identity)],
) -> TokenClaims:
    """App sessions only: payments and profile changes are not allowed from the kiosk."""
    if claims.scope != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only available in the app")
    return claims


async def optional_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims | None:
    return None if credentials is None else _claims(request, credentials)
