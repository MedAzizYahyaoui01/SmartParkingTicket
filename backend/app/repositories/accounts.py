"""Accounts store: users and their wallet, payments, and parking stays.

MongoDB in production, an in-memory twin for tests (same behaviour). The wallet balance
lives on the user document and only ever changes through `adjust_balance`, which is atomic
in MongoDB (a conditional $inc), so two payments at the same time can never overdraw it.
"""

import copy
from datetime import datetime
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

USERS = "users"
TRANSACTIONS = "wallet_transactions"
PAYMENTS = "payments"
STAYS = "parking_stays"


class DuplicateEmailError(Exception):
    """An account already exists with this e-mail."""


class AccountRepository(Protocol):
    async def init(self) -> None: ...
    async def create_user(self, user: dict[str, Any]) -> None: ...
    async def get_user(self, uid: str) -> dict[str, Any] | None: ...
    async def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...
    async def update_user(self, uid: str, fields: dict[str, Any]) -> None: ...

    async def adjust_balance(self, uid: str, delta: int, floor: int | None) -> int | None:
        """Adds `delta` (negative = debit) and returns the new balance. With a `floor`, the
        change is refused (returns None) if the balance would end below it."""
        ...

    async def insert_transaction(self, tx: dict[str, Any]) -> None: ...
    async def list_transactions(self, uid: str, limit: int) -> list[dict[str, Any]]: ...

    async def insert_payment(self, payment: dict[str, Any]) -> None: ...
    async def get_payment(self, payment_id: str) -> dict[str, Any] | None: ...
    async def update_payment(self, payment_id: str, fields: dict[str, Any]) -> None: ...
    async def list_payments(self, uid: str, limit: int) -> list[dict[str, Any]]: ...

    async def open_stay(self, stay: dict[str, Any]) -> None: ...
    async def get_open_stay(self, uid: str) -> dict[str, Any] | None: ...
    async def close_stay(self, stay_id: str, fields: dict[str, Any]) -> None: ...


class MongoAccountRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self.db = db

    async def init(self) -> None:
        await self.db[USERS].create_index("email", unique=True)
        await self.db[TRANSACTIONS].create_index([("uid", ASCENDING), ("ts", DESCENDING)])
        await self.db[PAYMENTS].create_index([("uid", ASCENDING), ("created_at", DESCENDING)])
        await self.db[STAYS].create_index([("uid", ASCENDING), ("status", ASCENDING)])

    async def create_user(self, user: dict[str, Any]) -> None:
        try:
            await self.db[USERS].insert_one(dict(user))
        except DuplicateKeyError as e:
            raise DuplicateEmailError(user["email"]) from e

    async def get_user(self, uid: str) -> dict[str, Any] | None:
        return await self.db[USERS].find_one({"_id": uid})

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return await self.db[USERS].find_one({"email": email})

    async def update_user(self, uid: str, fields: dict[str, Any]) -> None:
        await self.db[USERS].update_one({"_id": uid}, {"$set": fields})

    async def adjust_balance(self, uid: str, delta: int, floor: int | None) -> int | None:
        query: dict[str, Any] = {"_id": uid}
        if floor is not None:
            query["balance"] = {"$gte": floor - delta}
        user = await self.db[USERS].find_one_and_update(
            query, {"$inc": {"balance": delta}}, return_document=ReturnDocument.AFTER
        )
        return None if user is None else user["balance"]

    async def insert_transaction(self, tx: dict[str, Any]) -> None:
        await self.db[TRANSACTIONS].insert_one(dict(tx))

    async def list_transactions(self, uid: str, limit: int) -> list[dict[str, Any]]:
        cursor = self.db[TRANSACTIONS].find({"uid": uid}, sort=[("ts", DESCENDING)], limit=limit)
        return await cursor.to_list()

    async def insert_payment(self, payment: dict[str, Any]) -> None:
        await self.db[PAYMENTS].insert_one(dict(payment))

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        return await self.db[PAYMENTS].find_one({"_id": payment_id})

    async def update_payment(self, payment_id: str, fields: dict[str, Any]) -> None:
        await self.db[PAYMENTS].update_one({"_id": payment_id}, {"$set": fields})

    async def list_payments(self, uid: str, limit: int) -> list[dict[str, Any]]:
        cursor = self.db[PAYMENTS].find(
            {"uid": uid}, sort=[("created_at", DESCENDING)], limit=limit
        )
        return await cursor.to_list()

    async def open_stay(self, stay: dict[str, Any]) -> None:
        await self.db[STAYS].insert_one(dict(stay))

    async def get_open_stay(self, uid: str) -> dict[str, Any] | None:
        return await self.db[STAYS].find_one({"uid": uid, "status": "open"})

    async def close_stay(self, stay_id: str, fields: dict[str, Any]) -> None:
        await self.db[STAYS].update_one({"_id": stay_id}, {"$set": {"status": "closed", **fields}})


class InMemoryAccountRepository:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.transactions: list[dict[str, Any]] = []
        self.payments: dict[str, dict[str, Any]] = {}
        self.stays: dict[str, dict[str, Any]] = {}

    async def init(self) -> None:
        pass

    async def create_user(self, user: dict[str, Any]) -> None:
        if any(u["email"] == user["email"] for u in self.users.values()):
            raise DuplicateEmailError(user["email"])
        self.users[user["_id"]] = copy.deepcopy(user)

    async def get_user(self, uid: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.users.get(uid))

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        user = next((u for u in self.users.values() if u["email"] == email), None)
        return copy.deepcopy(user)

    async def update_user(self, uid: str, fields: dict[str, Any]) -> None:
        if uid in self.users:
            self.users[uid].update(copy.deepcopy(fields))

    async def adjust_balance(self, uid: str, delta: int, floor: int | None) -> int | None:
        user = self.users.get(uid)
        if user is None or (floor is not None and user["balance"] + delta < floor):
            return None
        user["balance"] += delta
        return user["balance"]

    async def insert_transaction(self, tx: dict[str, Any]) -> None:
        self.transactions.append(copy.deepcopy(tx))

    async def list_transactions(self, uid: str, limit: int) -> list[dict[str, Any]]:
        mine = [t for t in self.transactions if t["uid"] == uid]
        return copy.deepcopy(sorted(mine, key=_ts, reverse=True)[:limit])

    async def insert_payment(self, payment: dict[str, Any]) -> None:
        self.payments[payment["_id"]] = copy.deepcopy(payment)

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.payments.get(payment_id))

    async def update_payment(self, payment_id: str, fields: dict[str, Any]) -> None:
        if payment_id in self.payments:
            self.payments[payment_id].update(copy.deepcopy(fields))

    async def list_payments(self, uid: str, limit: int) -> list[dict[str, Any]]:
        mine = [p for p in self.payments.values() if p["uid"] == uid]
        mine.sort(key=lambda p: p["created_at"], reverse=True)
        return copy.deepcopy(mine[:limit])

    async def open_stay(self, stay: dict[str, Any]) -> None:
        self.stays[stay["_id"]] = copy.deepcopy(stay)

    async def get_open_stay(self, uid: str) -> dict[str, Any] | None:
        stay = next(
            (s for s in self.stays.values() if s["uid"] == uid and s["status"] == "open"), None
        )
        return copy.deepcopy(stay)

    async def close_stay(self, stay_id: str, fields: dict[str, Any]) -> None:
        if stay_id in self.stays:
            self.stays[stay_id].update(status="closed", **copy.deepcopy(fields))


def _ts(tx: dict[str, Any]) -> datetime:
    return tx["ts"]
