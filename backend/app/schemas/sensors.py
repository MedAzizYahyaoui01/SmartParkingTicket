"""Messages exchanged with the ESP32 (contract: docs/contracts/sensor-reading.schema.json)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SpotId = Literal["P1", "P2", "P3", "P4"]
BarrierState = Literal["closed", "opening", "open", "closing"]
BarrierAction = Literal["open", "close"]


class SpotReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spot_id: SpotId
    distance_cm: float = Field(ge=0, le=400)
    occupied: bool


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)
    spots: list[SpotReading] = Field(min_length=1)
    gate_car_detected: bool
    barrier_state: BarrierState

    @field_validator("spots")
    @classmethod
    def no_duplicate_spots(cls, spots: list[SpotReading]) -> list[SpotReading]:
        ids = [s.spot_id for s in spots]
        if len(ids) != len(set(ids)):
            raise ValueError("each spot_id may appear only once")
        return spots


class SensorResponse(BaseModel):
    """What the ESP32 gets back: the barrier command to apply ("none" = keep doing)."""

    barrier_command: Literal["open", "close", "none"]
    free_spots: int
    # "account": the ESP32 must not open on its own, only on a barrier_command
    gate_mode: Literal["auto", "account"] = "auto"
