"""History store: MongoDB (append-only), or an in-memory stand-in for tests.

Besides writing, it answers the statistics queries. In MongoDB they are aggregation
pipelines (grouping is done by the database); the in-memory twin computes the same
results in Python, so the statistics service can be tested without a database.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase

EVENTS = "occupancy_events"
SNAPSHOTS = "occupancy_snapshots"
BARRIER_EVENTS = "barrier_events"
RESERVATIONS = "reservations"
PREDICTIONS = "predictions"


class HistoryRepository(Protocol):
    async def init(self) -> None: ...
    async def ping(self) -> bool: ...
    async def insert_events(self, events: list[dict[str, Any]]) -> None: ...
    async def insert_snapshot(self, snapshot: dict[str, Any]) -> None: ...
    async def insert_barrier_event(self, event: dict[str, Any]) -> None: ...
    async def insert_reservation(self, reservation: dict[str, Any]) -> None: ...
    async def end_reservation(
        self, reservation_id: str, status: str, ended_at: datetime
    ) -> None: ...
    async def insert_predictions(self, predictions: list[dict[str, Any]]) -> None: ...

    # Statistics. Rates are averages of the minute snapshots.
    async def occupancy_series(
        self, start: datetime, end: datetime, step_min: int, tz: str
    ) -> list[dict[str, Any]]:
        """[{ts, rate}] — one point per `step_min` bucket, aligned on local time."""
        ...

    async def occupancy_by_weekday_hour(
        self, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        """[{weekday (0=Mon), hour, rate, samples}] in local time."""
        ...

    async def find_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Spot state changes in the period, oldest first."""
        ...


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
        await self.db[EVENTS].create_index("ts")
        await self.db[PREDICTIONS].create_index("ts")

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

    async def insert_reservation(self, reservation: dict[str, Any]) -> None:
        await self.db[RESERVATIONS].insert_one(dict(reservation))

    async def end_reservation(self, reservation_id: str, status: str, ended_at: datetime) -> None:
        await self.db[RESERVATIONS].update_one(
            {"_id": reservation_id}, {"$set": {"status": status, "ended_at": ended_at}}
        )

    async def insert_predictions(self, predictions: list[dict[str, Any]]) -> None:
        if predictions:
            await self.db[PREDICTIONS].insert_many([dict(p) for p in predictions])

    async def occupancy_series(
        self, start: datetime, end: datetime, step_min: int, tz: str
    ) -> list[dict[str, Any]]:
        bucket = {
            "$dateTrunc": {"date": "$ts", "unit": "minute", "binSize": step_min, "timezone": tz}
        }
        pipeline = [
            {"$match": {"ts": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": bucket, "rate": {"$avg": "$rate"}}},
            {"$sort": {"_id": 1}},
        ]
        cursor = await self.db[SNAPSHOTS].aggregate(pipeline)
        return [{"ts": d["_id"], "rate": d["rate"]} async for d in cursor]

    async def occupancy_by_weekday_hour(
        self, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        local = {"date": "$ts", "timezone": tz}
        pipeline = [
            {"$match": {"ts": {"$gte": start, "$lt": end}}},
            {
                "$group": {
                    "_id": {"weekday": {"$isoDayOfWeek": local}, "hour": {"$hour": local}},
                    "rate": {"$avg": "$rate"},
                    "samples": {"$sum": 1},
                }
            },
        ]
        cursor = await self.db[SNAPSHOTS].aggregate(pipeline)
        return [
            {
                "weekday": d["_id"]["weekday"] - 1,  # ISO 1=Monday -> 0=Monday
                "hour": d["_id"]["hour"],
                "rate": d["rate"],
                "samples": d["samples"],
            }
            async for d in cursor
        ]

    async def find_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cursor = self.db[EVENTS].find(
            {"ts": {"$gte": start, "$lt": end}}, {"_id": 0}, sort=[("ts", ASCENDING)]
        )
        return await cursor.to_list()


class InMemoryHistoryRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.barrier_events: list[dict[str, Any]] = []
        self.reservations: dict[str, dict[str, Any]] = {}
        self.predictions: list[dict[str, Any]] = []
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

    async def insert_reservation(self, reservation: dict[str, Any]) -> None:
        self._check()
        self.reservations[reservation["_id"]] = dict(reservation)

    async def end_reservation(self, reservation_id: str, status: str, ended_at: datetime) -> None:
        self._check()
        if reservation_id in self.reservations:
            self.reservations[reservation_id].update(status=status, ended_at=ended_at)

    async def insert_predictions(self, predictions: list[dict[str, Any]]) -> None:
        self._check()
        self.predictions.extend(predictions)

    def _snapshots_in(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._check()
        return [s for s in self.snapshots if start <= s["ts"] < end]

    async def occupancy_series(
        self, start: datetime, end: datetime, step_min: int, tz: str
    ) -> list[dict[str, Any]]:
        zone = ZoneInfo(tz)
        buckets: dict[datetime, list[float]] = defaultdict(list)
        for snap in self._snapshots_in(start, end):
            local = snap["ts"].astimezone(zone)
            midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
            minutes = (local - midnight) // timedelta(minutes=1)
            bucket = midnight + timedelta(minutes=minutes - minutes % step_min)
            buckets[bucket].append(snap["rate"])
        return [{"ts": ts, "rate": sum(r) / len(r)} for ts, r in sorted(buckets.items())]

    async def occupancy_by_weekday_hour(
        self, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        zone = ZoneInfo(tz)
        cells: dict[tuple[int, int], list[float]] = defaultdict(list)
        for snap in self._snapshots_in(start, end):
            local = snap["ts"].astimezone(zone)
            cells[(local.weekday(), local.hour)].append(snap["rate"])
        return [
            {"weekday": wd, "hour": h, "rate": sum(r) / len(r), "samples": len(r)}
            for (wd, h), r in cells.items()
        ]

    async def find_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._check()
        return sorted((e for e in self.events if start <= e["ts"] < end), key=lambda e: e["ts"])
