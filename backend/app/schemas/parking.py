"""Messages exchanged with the dashboard."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.sensors import BarrierAction, BarrierState

SpotStatus = Literal["free", "occupied", "reserved", "unknown"]


class SpotOut(BaseModel):
    spot_id: str
    status: SpotStatus
    distance_cm: float | None
    updated_at: int | None  # epoch seconds of the last status change


class SummaryOut(BaseModel):
    free: int
    occupied: int
    reserved: int
    total: int


class DeviceOut(BaseModel):
    online: bool
    last_seen: int | None


class ParkingOut(BaseModel):
    spots: list[SpotOut]
    summary: SummaryOut
    device: DeviceOut
    barrier_state: BarrierState
    gate_car_detected: bool


class BarrierCommandIn(BaseModel):
    action: BarrierAction


class BarrierCommandOut(BaseModel):
    action: BarrierAction
    source: str
    issued_at: int
    status: Literal["pending", "delivered"]
