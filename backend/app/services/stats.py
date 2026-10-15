"""Statistics for the dashboard, read from the MongoDB history (read-only)."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.repositories.history import HistoryRepository
from app.schemas.stats import (
    HeatmapCell,
    HourRate,
    OccupancyOut,
    OccupancyPoint,
    SummaryStatsOut,
)

# Bucket sizes that divide a day, so buckets line up on local midnight
ALLOWED_STEPS_MIN = (1, 5, 15, 30, 60, 120, 180, 360, 720, 1440)
MAX_RANGE = timedelta(days=92)


class StatsService:
    def __init__(self, history: HistoryRepository, tz: str) -> None:
        self.history = history
        self.tz = tz

    def localize(self, dt: datetime) -> datetime:
        """A date without a time zone is read as local time of the parking."""
        return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(self.tz))

    async def occupancy(self, start: datetime, end: datetime, step_min: int) -> OccupancyOut:
        start, end = self.localize(start), self.localize(end)
        _check_range(start, end)
        if step_min not in ALLOWED_STEPS_MIN:
            raise ValueError(f"step must be one of {ALLOWED_STEPS_MIN}")
        rows = await self.history.occupancy_series(start, end, step_min, self.tz)
        return OccupancyOut(
            start=start,
            end=end,
            step_min=step_min,
            points=[OccupancyPoint(ts=r["ts"], rate=round(r["rate"], 4)) for r in rows],
        )

    async def summary(self, start: datetime, end: datetime) -> SummaryStatsOut:
        start, end = self.localize(start), self.localize(end)
        _check_range(start, end)
        cells = await self.history.occupancy_by_weekday_hour(start, end, self.tz)
        events = await self.history.find_events(start, end)

        samples = sum(c["samples"] for c in cells)
        avg_rate = sum(c["rate"] * c["samples"] for c in cells) / samples if samples else None

        # Average by hour of the day, weighting each weekday by its number of snapshots
        by_hour = []
        for hour in range(24):
            same_hour = [c for c in cells if c["hour"] == hour]
            n = sum(c["samples"] for c in same_hour)
            if n:
                rate = sum(c["rate"] * c["samples"] for c in same_hour) / n
                by_hour.append(HourRate(hour=hour, rate=round(rate, 4)))
        peak_hours = sorted(by_hour, key=lambda h: h.rate, reverse=True)[:3]

        durations = _parking_durations_min(events)
        return SummaryStatsOut(
            start=start,
            end=end,
            timezone=self.tz,
            samples=samples,
            avg_rate=round(avg_rate, 4) if avg_rate is not None else None,
            entries=sum(1 for e in events if e["occupied"]),
            avg_duration_min=round(sum(durations) / len(durations), 1) if durations else None,
            peak_hours=peak_hours,
            by_hour=by_hour,
            heatmap=sorted(
                (
                    HeatmapCell(weekday=c["weekday"], hour=c["hour"], rate=round(c["rate"], 4))
                    for c in cells
                ),
                key=lambda c: (c.weekday, c.hour),
            ),
        )


def _check_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("'to' must be after 'from'")
    if end - start > MAX_RANGE:
        raise ValueError(f"the period can't exceed {MAX_RANGE.days} days")


def _parking_durations_min(events: list[dict[str, Any]]) -> list[float]:
    """Pairs each arrival on a spot with the next departure from it.
    A car already parked when the period starts, or still parked at its end, is ignored."""
    arrived: dict[str, datetime] = {}
    durations = []
    for e in events:  # oldest first
        if e["occupied"]:
            arrived[e["spot_id"]] = e["ts"]
        elif e["spot_id"] in arrived:
            durations.append((e["ts"] - arrived.pop(e["spot_id"])).total_seconds() / 60)
    return durations
