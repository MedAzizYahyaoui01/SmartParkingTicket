"""Simulated card gateway for wallet top-ups.

It behaves like a real one for the demo: a checkout is created first, then confirmed with a
card; the number must pass the Luhn check and the expiry date must be in the future.
Test cards (any future expiry, any CVC):

    4242 4242 4242 4242   Visa, success
    5555 5555 5555 4444   Mastercard, success
    4000 0000 0000 0002   declined
    4000 0000 0000 9995   insufficient funds
    4000 0000 0000 0069   expired card

Any other valid number succeeds. Only the brand and the last 4 digits are stored; the full
number and the CVC never leave this function.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.schemas.accounts import CardIn, PaymentOut
from app.services.accounts import AccountService

TEST_FAILURES = {
    "4000000000000002": "card_declined",
    "4000000000009995": "insufficient_funds",
    "4000000000000069": "expired_card",
}


class PaymentNotFoundError(Exception):
    pass


class PaymentAlreadyProcessedError(Exception):
    pass


class PaymentService:
    def __init__(self, accounts: AccountService) -> None:
        self.accounts = accounts
        self.repo = accounts.repo
        self.settings = accounts.settings

    async def checkout(self, uid: str, amount: int) -> PaymentOut:
        s = self.settings
        if not s.topup_min <= amount <= s.topup_max:
            raise ValueError(f"amount must be between {s.topup_min} and {s.topup_max} millimes")
        payment = {
            "_id": "pay_" + uuid.uuid4().hex[:16],
            "uid": uid,
            "amount": amount,
            "currency": s.currency,
            "status": "requires_payment",
            "created_at": self._now(),
        }
        await self.repo.insert_payment(payment)
        return _out(payment)

    async def confirm(self, uid: str, payment_id: str, card: CardIn) -> PaymentOut:
        async with self.accounts.locks(payment_id):
            payment = await self.repo.get_payment(payment_id)
            if payment is None or payment["uid"] != uid:
                raise PaymentNotFoundError(payment_id)
            if payment["status"] != "requires_payment":
                raise PaymentAlreadyProcessedError(payment_id)

            number = "".join(ch for ch in card.number if ch.isdigit())
            fields: dict[str, Any] = {"card_brand": _brand(number), "card_last4": number[-4:]}
            failure = self._check_card(number, card)
            if failure:
                fields.update(status="failed", failure_reason=failure)
            else:
                balance = await self.accounts.credit(
                    uid, payment["amount"], "topup", f"Top-up, card •••• {number[-4:]}", payment_id
                )
                now = self._now()
                fields.update(
                    status="succeeded",
                    paid_at=now,
                    balance_after=balance,
                    receipt_no=f"R-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                )
            await self.repo.update_payment(payment_id, fields)
            return _out({**payment, **fields})

    async def history(self, uid: str, limit: int = 20) -> list[PaymentOut]:
        return [_out(p) for p in await self.repo.list_payments(uid, limit)]

    def _check_card(self, number: str, card: CardIn) -> str | None:
        if not 12 <= len(number) <= 19 or not _luhn_ok(number):
            return "invalid_number"
        now = self._now()
        if (card.exp_year, card.exp_month) < (now.year, now.month):
            return "expired_card"
        return TEST_FAILURES.get(number)

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.accounts.clock(), UTC)


def _luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _brand(number: str) -> str:
    if number.startswith("4"):
        return "Visa"
    if number[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(number[:4] or 0) <= 2720:
        return "Mastercard"
    return "Card"


def _out(p: dict[str, Any]) -> PaymentOut:
    return PaymentOut(
        id=p["_id"],
        amount=p["amount"],
        currency=p["currency"],
        status=p["status"],
        created_at=p["created_at"],
        paid_at=p.get("paid_at"),
        card_brand=p.get("card_brand"),
        card_last4=p.get("card_last4"),
        failure_reason=p.get("failure_reason"),
        receipt_no=p.get("receipt_no"),
        balance_after=p.get("balance_after"),
    )
