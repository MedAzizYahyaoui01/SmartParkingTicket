"""Accounts, wallet, payments and the gate, as seen by the app and the kiosk.

Every amount is an integer number of millimes (1 TND = 1000 millimes): no floating point
anywhere near money.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.reservations import ReservationOut
from app.schemas.sensors import SpotId

Language = Literal["en", "fr", "ar"]
# ok: can enter; low: below the entry minimum; debt: negative balance (blocked until topped up)
AccountStatus = Literal["ok", "low", "debt"]


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    plate: str | None = Field(default=None, max_length=16)
    language: Language = "en"

    @field_validator("name", "plate")
    @classmethod
    def strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=40)
    plate: str | None = Field(default=None, max_length=16)
    language: Language | None = None


class StayOut(BaseModel):
    id: str
    started_at: datetime
    minutes: int  # so far
    fee_so_far: int  # what leaving now would cost


class UserOut(BaseModel):
    uid: str
    name: str
    email: str
    plate: str | None
    language: Language
    balance: int
    currency: str
    status: AccountStatus
    created_at: datetime
    stay: StayOut | None = None
    reservation: ReservationOut | None = None


class AuthOut(BaseModel):
    token: str
    expires_at: int  # epoch seconds
    user: UserOut


class TransactionOut(BaseModel):
    id: str
    kind: Literal["topup", "reservation_fee", "reservation_refund", "parking"]
    amount: int  # signed: credit > 0, debit < 0
    balance_after: int
    description: str
    ts: datetime


class PricingOut(BaseModel):
    currency: str
    hourly_rate: int
    free_minutes: int
    billing_block_min: int
    reservation_fee: int
    min_entry_balance: int
    topup_min: int
    topup_max: int
    gate_mode: Literal["auto", "account"]


class AccessCodeOut(BaseModel):
    """Shown in the app as a QR code (and as digits); scanned or typed at the gate kiosk."""

    code: str
    qr_payload: str
    expires_at: int


# --- payments (simulated card gateway) -----------------------------------------

PaymentStatus = Literal["requires_payment", "succeeded", "failed"]


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0)  # bounds come from the settings


class CardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=12, max_length=23)
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=2000, le=2100)
    cvc: str = Field(pattern=r"^\d{3,4}$")
    holder: str = Field(min_length=1, max_length=60)


class PaymentOut(BaseModel):
    id: str
    amount: int
    currency: str
    status: PaymentStatus
    created_at: datetime
    paid_at: datetime | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    failure_reason: str | None = None
    receipt_no: str | None = None
    balance_after: int | None = None


# --- gate ----------------------------------------------------------------------


class IdentifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The 6 digits, or the full QR payload ("SPGATE:123456")
    code: str = Field(min_length=6, max_length=32)


class KioskSessionOut(BaseModel):
    token: str
    expires_at: int
    user: UserOut


GateReason = Literal[
    "ok",
    "not_identified",
    "already_inside",
    "not_inside",
    "debt",
    "low_balance",
    "full",
]


class GateDecisionOut(BaseModel):
    allowed: bool
    reason: GateReason
    direction: Literal["entry", "exit"]
    balance: int | None = None
    fee: int | None = None  # exit only
    minutes: int | None = None  # exit only
    spot_hint: str | None = None  # entry: the reserved spot, if any
    device_online: bool = True


class AccountReservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spot_id: SpotId
    duration_min: int = Field(default=15, ge=1)
