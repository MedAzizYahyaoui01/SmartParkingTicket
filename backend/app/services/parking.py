"""Business rules of the parking.

This is the only place that decides what is written where:
- Firebase gets the *current* state (overwritten on every reading, pushed live to the browser);
- MongoDB gets the *history* (one document per real change, one snapshot per minute).

A failing database never makes a sensor reading fail: the ESP32 must always get its barrier
command back, so write errors are logged and the request carries on.

Spot status: the sensors give the *physical* status (free / occupied). A free spot with an
active reservation is shown as "reserved" and no longer counts as free (so the barrier
doesn't open for it). A car parking on a reserved spot fulfils the reservation.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.repositories.history import HistoryRepository
from app.repositories.realtime import RealtimeStore
from app.schemas.parking import (
    BarrierCommandOut,
    DeviceOut,
    ParkingOut,
    SpotOut,
    SummaryOut,
)
from app.schemas.reservations import ReservationOut
from app.schemas.sensors import SensorReading, SensorResponse

logger = logging.getLogger(__name__)


@dataclass
class SpotState:
    # "unknown" until the first reading (or the Firebase copy) says otherwise
    status: str = "unknown"
    distance_cm: float | None = None
    updated_at: float | None = None  # time of the last *status change*

    def to_firebase(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "distance_cm": self.distance_cm,
            "updated_at": int(self.updated_at) if self.updated_at else None,
        }


@dataclass
class Reservation:
    id: str
    spot_id: str
    name: str
    created_at: float
    expires_at: float

    def to_firebase(self) -> dict[str, Any]:
        return {
            "spot_id": self.spot_id,
            "name": self.name,
            "created_at": int(self.created_at),
            "expires_at": int(self.expires_at),
        }

    def out(self, status: str = "active") -> ReservationOut:
        return ReservationOut(id=self.id, status=status, **self.to_firebase())


class SpotUnavailableError(Exception):
    """The spot can't be reserved (occupied, already reserved, or state unknown)."""


class ReservationNotFoundError(Exception):
    """No active reservation with this ID."""


@dataclass
class PendingCommand:
    action: str
    source: str
    issued_at: float


class ParkingService:
    def __init__(
        self,
        store: RealtimeStore,
        history: HistoryRepository,
        settings: Settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.history = history
        self.settings = settings
        self.clock = clock

        self.spots: dict[str, SpotState] = {sid: SpotState() for sid in settings.spot_ids}
        self.device_id: str | None = None
        self.last_seen: float | None = None
        self.online = False
        self.barrier_state = "closed"
        self.gate_car = False
        self.pending_command: PendingCommand | None = None
        self.reservations: dict[str, Reservation] = {}  # active ones only
        self._last_command_source = "device"  # who caused the next barrier movement
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ start-up

    async def startup(self) -> None:
        """Prepares MongoDB and restores the last known spot states from Firebase,
        so an API restart doesn't record every spot as a new change."""
        await self._record(self.history.init)

        try:
            saved = await asyncio.to_thread(self.store.get, "parking/spots")
        except Exception:
            logger.exception("Could not read the saved spot states")
            saved = None
        for spot_id, data in (saved or {}).items():
            if spot_id in self.spots and isinstance(data, dict):
                if data.get("status") in ("free", "occupied", "reserved"):
                    self.spots[spot_id] = SpotState(
                        # "reserved" is a free spot; the reservation itself is restored below
                        status="occupied" if data["status"] == "occupied" else "free",
                        distance_cm=data.get("distance_cm"),
                        updated_at=data.get("updated_at"),
                    )

        try:
            saved = await asyncio.to_thread(self.store.get, "reservations")
        except Exception:
            logger.exception("Could not read the saved reservations")
            saved = None
        for res_id, data in (saved or {}).items():
            try:
                self.reservations[res_id] = Reservation(id=res_id, **data)
            except TypeError:
                logger.warning("Ignoring malformed reservation %s in Firebase", res_id)
        # (Reservations that expired while the API was down end at the next expiry check.)

        # The device is offline until it reports again.
        await self._write(
            {"parking/device/online": False, "parking/summary": self.summary().model_dump()}
        )

    # ------------------------------------------------------------------ ESP32

    async def handle_reading(self, reading: SensorReading) -> SensorResponse:
        async with self._lock:
            now = self.clock()
            ts = _utc(now)

            # 1. Change detection: only a real change becomes a history event.
            events = []
            fulfilled: list[Reservation] = []
            for r in reading.spots:
                spot = self.spots[r.spot_id]
                new_status = "occupied" if r.occupied else "free"
                if spot.status != new_status:
                    if spot.status != "unknown":  # first sighting is not a change
                        events.append(
                            {
                                "spot_id": r.spot_id,
                                "occupied": r.occupied,
                                "distance_cm": r.distance_cm,
                                "ts": ts,
                            }
                        )
                    spot.status = new_status
                    spot.updated_at = now
                spot.distance_cm = r.distance_cm
                # A car parked on a reserved spot: the reservation is used.
                res = self._reservation_for(r.spot_id)
                if res and r.occupied:
                    del self.reservations[res.id]
                    fulfilled.append(res)

            # The barrier started opening (or closing) if it went from the closed side to the
            # open side (or back). "opening"/"open" both count, in case a step is skipped.
            was_open = self.barrier_state in ("opening", "open")
            is_open = reading.barrier_state in ("opening", "open")
            barrier_moved = was_open != is_open
            self.barrier_state = reading.barrier_state
            self.gate_car = reading.gate_car_detected
            self.device_id = reading.device_id
            self.last_seen = now
            self.online = True

            # 2. Barrier command for the ESP32.
            command, delivered = self._decide_command(reading)

            # 3. Current state -> Firebase, in a single multi-path update.
            updates: dict[str, Any] = {
                f"parking/spots/{sid}": self._spot_firebase(sid)
                for sid, s in self.spots.items()
                if s.status != "unknown"
            }
            for res in fulfilled:
                updates[f"reservations/{res.id}"] = None
            updates["parking/summary"] = self.summary().model_dump()
            updates["parking/device"] = {
                "online": True,
                "last_seen": int(now),
                "device_id": reading.device_id,
            }
            updates["parking/gate_car_detected"] = reading.gate_car_detected
            updates["barrier/state"] = reading.barrier_state
            if delivered:
                updates["barrier/command/status"] = "delivered"
            await self._write(updates)

            # 4. History -> MongoDB.
            if events:
                await self._record(self.history.insert_events, events)
            if barrier_moved:
                await self._record(
                    self.history.insert_barrier_event,
                    {
                        "action": "open" if is_open else "close",
                        "source": self._last_command_source,
                        "ts": ts,
                    },
                )
                self._last_command_source = "device"
            for res in fulfilled:
                await self._record(self.history.end_reservation, res.id, "fulfilled", ts)

            return SensorResponse(barrier_command=command, free_spots=self.free_count())

    def _decide_command(self, reading: SensorReading) -> tuple[str, bool]:
        """Returns (command, whether a dashboard command was just delivered)."""
        # A manual command from the dashboard wins, and is delivered once.
        if self.pending_command is not None:
            cmd = self.pending_command
            self.pending_command = None
            self._last_command_source = cmd.source
            return cmd.action, True

        # Automatic rule: a car waits at the gate and there is a free spot.
        if (
            reading.gate_car_detected
            and reading.barrier_state in ("closed", "closing")
            and self.free_count() > 0
        ):
            self._last_command_source = "auto"
            return "open", False

        return "none", False

    # ------------------------------------------------------------------ dashboard

    async def submit_barrier_command(
        self, action: str, source: str = "dashboard"
    ) -> BarrierCommandOut:
        """Queues a manual command; the ESP32 receives it in its next response."""
        async with self._lock:
            now = self.clock()
            self.pending_command = PendingCommand(action=action, source=source, issued_at=now)
            out = BarrierCommandOut(
                action=action, source=source, issued_at=int(now), status="pending"
            )
            await self._write({"barrier/command": out.model_dump()})
            return out

    def get_state(self) -> ParkingOut:
        return ParkingOut(
            spots=[
                SpotOut(
                    spot_id=sid,
                    status=self._effective_status(sid),
                    distance_cm=s.distance_cm,
                    updated_at=int(s.updated_at) if s.updated_at else None,
                )
                for sid, s in self.spots.items()
            ],
            summary=self.summary(),
            device=DeviceOut(
                online=self.online,
                last_seen=int(self.last_seen) if self.last_seen else None,
            ),
            barrier_state=self.barrier_state,
            gate_car_detected=self.gate_car,
        )

    # ------------------------------------------------------------------ reservations

    async def create_reservation(
        self, spot_id: str, name: str, duration_min: int | None = None
    ) -> ReservationOut:
        duration_min = duration_min or self.settings.reservation_default_min
        if duration_min > self.settings.reservation_max_min:
            raise ValueError(f"duration_min must be at most {self.settings.reservation_max_min}")
        async with self._lock:
            if self._reservation_for(spot_id):
                raise SpotUnavailableError(f"{spot_id} is already reserved")
            status = self.spots[spot_id].status
            if status != "free":
                raise SpotUnavailableError(f"{spot_id} is {status}")

            now = self.clock()
            res = Reservation(
                id=uuid.uuid4().hex[:12],
                spot_id=spot_id,
                name=name.strip(),
                created_at=now,
                expires_at=now + duration_min * 60,
            )
            self.reservations[res.id] = res
            await self._write(
                {
                    f"reservations/{res.id}": res.to_firebase(),
                    f"parking/spots/{spot_id}": self._spot_firebase(spot_id),
                    "parking/summary": self.summary().model_dump(),
                }
            )
            await self._record(
                self.history.insert_reservation,
                {
                    "_id": res.id,
                    "spot_id": spot_id,
                    "name": res.name,
                    "created_at": _utc(res.created_at),
                    "expires_at": _utc(res.expires_at),
                    "status": "active",
                },
            )
            return res.out()

    async def cancel_reservation(self, reservation_id: str) -> None:
        async with self._lock:
            res = self.reservations.get(reservation_id)
            if res is None:
                raise ReservationNotFoundError(reservation_id)
            await self._end_reservation(res, "cancelled")

    async def expire_reservations(self) -> list[str]:
        """Releases the reservations whose time is up. Returns their IDs."""
        async with self._lock:
            now = self.clock()
            expired = [r for r in self.reservations.values() if r.expires_at <= now]
            for res in expired:
                await self._end_reservation(res, "expired")
            return [r.id for r in expired]

    def list_reservations(self) -> list[ReservationOut]:
        return [r.out() for r in sorted(self.reservations.values(), key=lambda r: r.created_at)]

    async def _end_reservation(self, res: Reservation, status: str) -> None:
        """Must be called with the lock held."""
        del self.reservations[res.id]
        await self._write(
            {
                f"reservations/{res.id}": None,
                f"parking/spots/{res.spot_id}": self._spot_firebase(res.spot_id),
                "parking/summary": self.summary().model_dump(),
            }
        )
        await self._record(self.history.end_reservation, res.id, status, _utc(self.clock()))

    def _reservation_for(self, spot_id: str) -> Reservation | None:
        return next((r for r in self.reservations.values() if r.spot_id == spot_id), None)

    # ------------------------------------------------------------------ background tasks

    async def check_device_online(self) -> bool:
        """Marks the device offline after N seconds without a reading.
        Returns True if it has just gone offline."""
        async with self._lock:
            if not self.online or self.last_seen is None:
                return False
            if self.clock() - self.last_seen <= self.settings.device_offline_after_s:
                return False
            self.online = False
            logger.warning(
                "Device %s is offline (no reading for %ss)",
                self.device_id,
                self.settings.device_offline_after_s,
            )
            await self._write({"parking/device/online": False})
            return True

    async def take_snapshot(self) -> dict[str, Any] | None:
        """Stores the global occupancy rate — the time series the AI learns from.
        Skipped while the device is offline or the state is not fully known, so the
        training data never contains made-up values."""
        async with self._lock:
            if not self.online or any(s.status == "unknown" for s in self.spots.values()):
                return None
            total = len(self.spots)
            occupied = sum(1 for s in self.spots.values() if s.status == "occupied")
            snapshot = {
                "ts": _utc(self.clock()),
                "occupied": occupied,
                "total": total,
                "rate": round(occupied / total, 4),
            }
        await self._record(self.history.insert_snapshot, snapshot)
        return snapshot

    # ------------------------------------------------------------------ helpers

    def _effective_status(self, spot_id: str) -> str:
        """Physical status, except that a free spot with a reservation shows "reserved"."""
        status = self.spots[spot_id].status
        if status == "free" and self._reservation_for(spot_id):
            return "reserved"
        return status

    def _spot_firebase(self, spot_id: str) -> dict[str, Any]:
        return {**self.spots[spot_id].to_firebase(), "status": self._effective_status(spot_id)}

    def free_count(self) -> int:
        return sum(1 for sid in self.spots if self._effective_status(sid) == "free")

    def summary(self) -> SummaryOut:
        statuses = [self._effective_status(sid) for sid in self.spots]
        occupied = statuses.count("occupied")
        reserved = statuses.count("reserved")
        return SummaryOut(
            free=self.free_count(), occupied=occupied, reserved=reserved, total=len(self.spots)
        )

    async def _write(self, updates: dict[str, Any]) -> None:
        try:
            # firebase-admin is synchronous (HTTP): run it in a thread, not on the event loop.
            await asyncio.to_thread(self.store.update, updates)
        except Exception:
            logger.exception("Live state write failed")

    async def _record(self, func: Callable[..., Awaitable[None]], *args: Any) -> None:
        try:
            await func(*args)
        except Exception:
            logger.exception("History write failed (%s)", getattr(func, "__name__", func))


def _utc(epoch_s: float) -> datetime:
    return datetime.fromtimestamp(epoch_s, UTC)
