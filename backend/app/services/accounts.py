"""Accounts and the prepaid wallet.

Rules:
- The wallet is prepaid. A reservation fee needs the credit up front. A parking stay is
  charged on the way out, and that charge may push the balance below zero: a car is never
  trapped inside. A negative balance ("debt") blocks new entries and reservations until the
  user tops up.
- Every balance change writes a transaction (the wallet statement).
- Operations of one user (reserve, enter, leave) run one at a time, so a double tap in the app
  and a voice command at the kiosk can't both go through.
"""

import asyncio
import math
import secrets
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.repositories.accounts import AccountRepository, DuplicateEmailError
from app.schemas.accounts import (
    AccessCodeOut,
    AccountStatus,
    PricingOut,
    StayOut,
    TransactionOut,
    UserOut,
)
from app.schemas.reservations import ReservationOut
from app.security import create_token, hash_password, new_uid, verify_password
from app.services.parking import ParkingService, ReservationNotFoundError

QR_PREFIX = "SPGATE:"


class InvalidCredentialsError(Exception):
    pass


class EmailTakenError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class InsufficientFundsError(Exception):
    def __init__(self, needed: int, balance: int) -> None:
        super().__init__(f"needs {needed}, balance is {balance}")
        self.needed = needed
        self.balance = balance


class AccountBlockedError(Exception):
    """The account owes money (negative balance), or the action needs the user outside."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AlreadyReservedError(Exception):
    pass


class InvalidAccessCodeError(Exception):
    pass


class TooManyAttemptsError(Exception):
    pass


class KeyedLocks:
    """One asyncio lock per key (user, payment...)."""

    def __init__(self) -> None:
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __call__(self, key: str) -> asyncio.Lock:
        return self._locks[key]


class AccountService:
    def __init__(
        self,
        repo: AccountRepository,
        parking: ParkingService,
        settings: Settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo = repo
        self.parking = parking
        self.settings = settings
        self.clock = clock
        self.locks = KeyedLocks()
        self._codes: dict[str, tuple[str, float]] = {}  # code -> (uid, expires_at)
        self._failed_identify: defaultdict[str, list[float]] = defaultdict(list)

    async def startup(self) -> None:
        await self.repo.init()

    # ------------------------------------------------------------------ sign-up / sign-in

    async def register(
        self, name: str, email: str, password: str, plate: str | None, language: str
    ) -> dict[str, Any]:
        user = {
            "_id": new_uid(),
            "name": name,
            "email": email.lower(),
            "password_hash": hash_password(password),
            "plate": plate or None,
            "language": language,
            "balance": 0,
            "created_at": self._now(),
        }
        try:
            await self.repo.create_user(user)
        except DuplicateEmailError as e:
            raise EmailTakenError(email) from e
        return user

    async def login(self, email: str, password: str) -> dict[str, Any]:
        user = await self.repo.get_user_by_email(email.lower())
        # scrypt runs even for an unknown e-mail, so timing doesn't reveal which accounts exist
        stored = user["password_hash"] if user else hash_password(secrets.token_hex(8))
        if not verify_password(password, stored) or user is None:
            raise InvalidCredentialsError()
        return user

    def issue_token(self, uid: str, scope: str = "user") -> tuple[str, int]:
        ttl = (
            self.settings.token_ttl_h * 3600
            if scope == "user"
            else self.settings.kiosk_token_ttl_min * 60
        )
        # Wall-clock time on purpose: tokens are checked against it when they come back
        now = time.time()
        token = create_token(uid, scope, ttl, self.settings.jwt_secret, now=now)
        return token, int(now + ttl)

    async def get_user(self, uid: str) -> dict[str, Any]:
        user = await self.repo.get_user(uid)
        if user is None:
            raise UserNotFoundError(uid)
        return user

    async def update_profile(self, uid: str, fields: dict[str, Any]) -> dict[str, Any]:
        changes = {k: v for k, v in fields.items() if v is not None}
        if changes:
            await self.repo.update_user(uid, changes)
        return await self.get_user(uid)

    async def user_out(self, user: dict[str, Any]) -> UserOut:
        stay = await self.repo.get_open_stay(user["_id"])
        return UserOut(
            uid=user["_id"],
            name=user["name"],
            email=user["email"],
            plate=user.get("plate"),
            language=user.get("language", "en"),
            balance=user["balance"],
            currency=self.settings.currency,
            status=self.status_of(user["balance"]),
            created_at=user["created_at"],
            stay=self._stay_out(stay) if stay else None,
            reservation=self.parking.reservation_of_user(user["_id"]),
        )

    def status_of(self, balance: int) -> AccountStatus:
        if balance < 0:
            return "debt"
        if balance < self.settings.min_entry_balance:
            return "low"
        return "ok"

    # ------------------------------------------------------------------ pricing

    def pricing(self) -> PricingOut:
        s = self.settings
        return PricingOut(
            currency=s.currency,
            hourly_rate=s.hourly_rate,
            free_minutes=s.free_minutes,
            billing_block_min=s.billing_block_min,
            reservation_fee=s.reservation_fee,
            min_entry_balance=s.min_entry_balance,
            topup_min=s.topup_min,
            topup_max=s.topup_max,
            gate_mode=s.gate_mode,
        )

    def parking_fee(self, minutes: int) -> int:
        """Free for the first minutes, then every started block is charged pro rata."""
        s = self.settings
        if minutes <= s.free_minutes:
            return 0
        blocks = math.ceil((minutes - s.free_minutes) / s.billing_block_min)
        return round(blocks * s.hourly_rate * s.billing_block_min / 60)

    def stay_minutes(self, stay: dict[str, Any]) -> int:
        elapsed = self.clock() - stay["started_at"].timestamp()
        return max(1, math.ceil(elapsed / 60))

    def _stay_out(self, stay: dict[str, Any]) -> StayOut:
        minutes = self.stay_minutes(stay)
        return StayOut(
            id=stay["_id"],
            started_at=stay["started_at"],
            minutes=minutes,
            fee_so_far=self.parking_fee(minutes),
        )

    # ------------------------------------------------------------------ wallet

    async def credit(self, uid: str, amount: int, kind: str, description: str, ref: str) -> int:
        balance = await self.repo.adjust_balance(uid, amount, floor=None)
        if balance is None:
            raise UserNotFoundError(uid)
        await self._log(uid, kind, amount, balance, description, ref)
        return balance

    async def debit(
        self,
        uid: str,
        amount: int,
        kind: str,
        description: str,
        ref: str,
        allow_negative: bool = False,
    ) -> int:
        balance = await self.repo.adjust_balance(uid, -amount, floor=None if allow_negative else 0)
        if balance is None:
            user = await self.get_user(uid)
            raise InsufficientFundsError(amount, user["balance"])
        await self._log(uid, kind, -amount, balance, description, ref)
        return balance

    async def transactions(self, uid: str, limit: int = 50) -> list[TransactionOut]:
        rows = await self.repo.list_transactions(uid, limit)
        return [
            TransactionOut(
                id=t["_id"],
                kind=t["kind"],
                amount=t["amount"],
                balance_after=t["balance_after"],
                description=t["description"],
                ts=t["ts"],
            )
            for t in rows
        ]

    async def _log(
        self, uid: str, kind: str, amount: int, balance: int, description: str, ref: str
    ) -> None:
        await self.repo.insert_transaction(
            {
                "_id": uuid.uuid4().hex,
                "uid": uid,
                "kind": kind,
                "amount": amount,
                "balance_after": balance,
                "description": description,
                "ref": ref,
                "ts": self._now(),
            }
        )

    # ------------------------------------------------------------------ reservations

    async def reserve(self, uid: str, spot_id: str, duration_min: int) -> ReservationOut:
        async with self.locks(uid):
            user = await self.get_user(uid)
            if user["balance"] < 0:
                raise AccountBlockedError("debt")
            if await self.repo.get_open_stay(uid):
                raise AccountBlockedError("already_inside")
            if self.parking.reservation_of_user(uid):
                raise AlreadyReservedError()

            fee = self.settings.reservation_fee
            ref = uuid.uuid4().hex[:12]
            if fee:
                await self.debit(uid, fee, "reservation_fee", f"Reservation of {spot_id}", ref)
            try:
                return await self.parking.create_reservation(
                    spot_id, user["name"], duration_min, user_id=uid
                )
            except Exception:
                if fee:  # the spot was taken meanwhile (or bad duration): give the fee back
                    await self.credit(
                        uid, fee, "reservation_refund", f"Reservation of {spot_id} failed", ref
                    )
                raise

    async def cancel_reservation(self, uid: str, reservation_id: str) -> None:
        async with self.locks(uid):
            if self.parking.reservation_owner(reservation_id) != uid:
                raise ReservationNotFoundError(reservation_id)
            res = self.parking.reservation_of_user(uid)
            await self.parking.cancel_reservation(reservation_id)
            if self.settings.reservation_fee:
                spot = res.spot_id if res else "?"
                await self.credit(
                    uid,
                    self.settings.reservation_fee,
                    "reservation_refund",
                    f"Reservation of {spot} cancelled",
                    reservation_id,
                )

    # ------------------------------------------------------------------ gate access codes

    def new_access_code(self, uid: str) -> AccessCodeOut:
        """A fresh 6-digit code for this user (the previous one stops working)."""
        now = self.clock()
        self._purge_codes(now)
        for code, (owner, _) in list(self._codes.items()):
            if owner == uid:
                del self._codes[code]
        while True:
            code = f"{secrets.randbelow(10**6):06d}"
            if code not in self._codes:
                break
        expires = now + self.settings.access_code_ttl_s
        self._codes[code] = (uid, expires)
        return AccessCodeOut(code=code, qr_payload=QR_PREFIX + code, expires_at=int(expires))

    def redeem_access_code(self, raw: str, client: str) -> str:
        """Returns the uid behind a code (single use). At most 5 wrong codes per minute per
        client, so the 10^6 codes can't be guessed in their 2-minute lifetime."""
        now = self.clock()
        attempts = [t for t in self._failed_identify[client] if now - t < 60]
        self._failed_identify[client] = attempts
        if len(attempts) >= 5:
            raise TooManyAttemptsError()

        code = raw.strip().removeprefix(QR_PREFIX).strip()
        self._purge_codes(now)
        entry = self._codes.pop(code, None)
        if entry is None:
            attempts.append(now)
            raise InvalidAccessCodeError()
        return entry[0]

    def _purge_codes(self, now: float) -> None:
        for code, (_, expires) in list(self._codes.items()):
            if expires <= now:
                del self._codes[code]

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)
