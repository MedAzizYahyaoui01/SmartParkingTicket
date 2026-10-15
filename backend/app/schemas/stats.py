"""Statistics computed from the MongoDB history."""

from datetime import datetime

from pydantic import BaseModel


class OccupancyPoint(BaseModel):
    ts: datetime  # start of the bucket
    rate: float  # average occupancy rate in the bucket, 0..1


class OccupancyOut(BaseModel):
    start: datetime
    end: datetime
    step_min: int
    points: list[OccupancyPoint]


class HourRate(BaseModel):
    hour: int  # 0..23, local time
    rate: float


class HeatmapCell(BaseModel):
    weekday: int  # 0 = Monday .. 6 = Sunday, local time
    hour: int
    rate: float


class SummaryStatsOut(BaseModel):
    start: datetime
    end: datetime
    timezone: str
    samples: int  # number of minute snapshots behind the rates
    avg_rate: float | None
    entries: int  # cars that parked (a spot going free -> occupied)
    avg_duration_min: float | None  # average time a car stays on a spot
    peak_hours: list[HourRate]  # the 3 busiest hours of the day
    by_hour: list[HourRate]
    heatmap: list[HeatmapCell]
