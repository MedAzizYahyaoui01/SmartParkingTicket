from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_stats
from app.schemas.stats import OccupancyOut, SummaryStatsOut
from app.services.stats import StatsService

router = APIRouter(prefix="/stats", tags=["statistics"])

# "from" is a Python keyword, hence the aliases. Dates are ISO 8601; without a time zone
# they are read as local time of the parking. Default period: the last 24 hours.
FromParam = Annotated[datetime | None, Query(alias="from")]
ToParam = Annotated[datetime | None, Query(alias="to")]


def _period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = end or datetime.now(UTC)
    return start or end - timedelta(days=1), end


@router.get("/occupancy", response_model=OccupancyOut)
async def occupancy(
    stats: Annotated[StatsService, Depends(get_stats)],
    start: FromParam = None,
    end: ToParam = None,
    step: Annotated[int, Query(description="Bucket size in minutes")] = 15,
) -> OccupancyOut:
    """Average occupancy rate (0..1) per time bucket, for the occupancy chart."""
    try:
        return await stats.occupancy(*_period(start, end), step)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.get("/summary", response_model=SummaryStatsOut)
async def summary(
    stats: Annotated[StatsService, Depends(get_stats)],
    start: FromParam = None,
    end: ToParam = None,
) -> SummaryStatsOut:
    """Average occupancy, entries, average parking time, peak hours and the
    weekday x hour heatmap for the period."""
    try:
        return await stats.summary(*_period(start, end))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
