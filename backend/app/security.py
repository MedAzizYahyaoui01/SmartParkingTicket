"""Passwords and access tokens.

Passwords are hashed with scrypt (standard library), each with its own random salt.
Tokens are signed JWTs. Their "scope" says what they open:
- "user": the account holder, from the app (everything, payments included);
- "kiosk": a short session opened at the gate by scanning the account's QR code
  (the assistant, the gate and reservations, but no payment and no profile change).
"""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Literal

import jwt

Scope = Literal["user", "kiosk"]

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=_unb64(salt), **_SCRYPT)
    return hmac.compare_digest(candidate, _unb64(digest))


@dataclass(frozen=True)
class TokenClaims:
    uid: str
    scope: Scope
    expires_at: int


class InvalidTokenError(Exception):
    pass


def create_token(uid: str, scope: Scope, ttl_s: int, secret: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    claims = {"sub": uid, "scope": scope, "iat": int(now), "exp": int(now + ttl_s)}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> TokenClaims:
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    if claims.get("scope") not in ("user", "kiosk") or not claims.get("sub"):
        raise InvalidTokenError("unexpected token claims")
    return TokenClaims(uid=claims["sub"], scope=claims["scope"], expires_at=claims["exp"])


# Account UIDs: "SP-" + 8 characters, without look-alikes (0/O, 1/I/L) so they can be read
# out loud or typed at the kiosk.
_UID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_uid() -> str:
    return "SP-" + "".join(secrets.choice(_UID_ALPHABET) for _ in range(8))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
