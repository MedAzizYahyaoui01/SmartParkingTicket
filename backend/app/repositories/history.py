"""History store: MongoDB (append-only), or an in-memory stand-in for tests."""

from typing import Any, Protocol

from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase

EVENTS = "occupancy_events"
SNAPSHOTS = "occupancy_snapshots"
BARRIER_EVENTS = "barrier_events"


class HistoryRepository(Protocol):
    async def init(self) -> None: ...
    async def ping(self) -> bool: ...
    async def insert_events(self, events: list[dict[str, Any]]) -> None: ...
    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None: ...
    async def insert_barrier_event(self, event: dict[str, Any]) -> None: ...


class MongoHistoryRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self.db = db

    async def init(self) -> None:
        """Creates the collections and indexes once (safe to call at every start-up)."""
        existing = await self.db.list_collection_names()
        if SNAPSHOTS not in existing:
            # Native time-series collection: compact storage, fast range queries.
            await self.db.create_collection(
                SNAPSHOTS, timeseries={"timeField": "ts", "granularity": "minutes"}
            )
        await self.db[EVENTS].create_index([("spot_id", ASCENDING), ("ts", ASCENDING)])
        await self.db[BARRIER_EVENTS].create_index("ts")

    async def ping(self) -> bool:
        try:
            await self.db.command("ping")
            return True
        except Exception:
            return False

    async def insert_events(self, events: list[dict[str, Any]]) -> None:
        if events:
            # copies: insert_many adds an _id to each dict it is given
            await self.db[EVENTS].insert_many([dict(e) for e in events])

    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        await self.db[SNAPSHOTS].insert_one(dict(snapshot))

    async def insert_barrier_event(self, event: dict[str, Any]) -> None:
        await self.db[BARRIER_EVENTS].insert_one(dict(event))


class InMemoryHistoryRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.barrier_events: list[dict[str, Any]] = []
        self.available = True  # set to False in tests to simulate MongoDB being down

    def _check(self) -> None:
        if not self.available:
            raise ConnectionError("history database unavailable")

    async def init(self) -> None:
        self._check()

    async def ping(self) -> bool:
        return self.available

    async def insert_events(self, events: list[dict[str, Any]]) -> None:
        self._check()
        self.events.extend(events)

    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._check()
        self.snapshots.append(snapshot)

    async def insert_barrier_event(self, event: dict[str, Any]) -> None:
        self._check()
        self.barrier_events.append(event)
