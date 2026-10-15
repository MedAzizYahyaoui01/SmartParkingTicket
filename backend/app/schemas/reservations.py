"""Simulated reservations made from the dashboard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sensors import SpotId

ReservationStatus = Literal["active", "fulfilled", "cancelled", "expired"]


class ReservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    spot_id: SpotId
    # Upper bound checked by the service (it comes from the settings)
    duration_min: int = Field(default=15, ge=1)


class ReservationOut(BaseModel):
    id: str
    spot_id: str
    name: str
    created_at: int  # epoch seconds
    expires_at: int
    status: ReservationStatus
