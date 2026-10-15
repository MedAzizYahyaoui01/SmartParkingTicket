"""Statistics: computations (service) and query parameters (API)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.stats import StatsService

# Monday 2026-10-12, 08:00 UTC = 09:00 in Africa/Tunis (UTC+1, no daylight saving)
MONDAY_8H_UTC = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


def snap(ts: datetime, rate: float) -> dict:
    return {"ts": ts, "occupied": round(rate * 4), "total": 4, "rate": rate}


def event(spot: str, occupied: bool, ts: datetime) -> dict:
    return {"spot_id": spot, "occupied": occupied, "distance_cm": 20.0, "ts": ts}


@pytest.fixture
def stats(history) -> StatsService:
    return StatsService(history, "Africa/Tunis")


async def test_occupancy_is_averaged_per_bucket(stats, history):
    # 30 minutes of snapshots: 0.25 for the first 15 min, 0.75 for the next 15
    for minute in range(30):
        rate = 0.25 if minute < 15 else 0.75
        history.snapshots.append(snap(MONDAY_8H_UTC + timedelta(minutes=minute), rate))

    out = await stats.occupancy(MONDAY_8H_UTC, MONDAY_8H_UTC + timedelta(hours=1), 15)

    assert [p.rate for p in out.points] == [0.25, 0.75]
    assert out.points[0].ts == MONDAY_8H_UTC
    assert out.points[1].ts - out.points[0].ts == timedelta(minutes=15)


async def test_period_bounds_are_start_inclusive_end_exclusive(stats, history):
    history.snapshots += [snap(MONDAY_8H_UTC, 1.0), snap(MONDAY_8H_UTC + timedelta(hours=1), 0.0)]

    out = await stats.occupancy(MONDAY_8H_UTC, MONDAY_8H_UTC + timedelta(hours=1), 60)

    assert [p.rate for p in out.points] == [1.0]


async def test_summary_uses_local_hour_and_weekday(stats, history):
    history.snapshots += [snap(MONDAY_8H_UTC + timedelta(minutes=m), 0.5) for m in range(60)]

    out = await stats.summary(MONDAY_8H_UTC - timedelta(hours=1), MONDAY_8H_UTC + timedelta(days=1))

    assert out.samples == 60
    assert out.avg_rate == 0.5
    assert [(c.weekday, c.hour) for c in out.heatmap] == [(0, 9)]  # Monday, 09:00 local
    assert out.by_hour[0].hour == 9


async def test_summary_peak_hours_are_the_three_busiest(stats, history):
    for hour, rate in [(7, 0.2), (8, 0.9), (12, 0.8), (13, 0.7), (20, 0.1)]:
        history.snapshots.append(snap(MONDAY_8H_UTC.replace(hour=hour), rate))

    out = await stats.summary(MONDAY_8H_UTC.replace(hour=0), MONDAY_8H_UTC.replace(hour=23))

    # UTC hours 8, 12, 13 -> local 9, 13, 14
    assert [h.hour for h in out.peak_hours] == [9, 13, 14]


async def test_entries_and_average_parking_time(stats, history):
    t = MONDAY_8H_UTC
    history.events += [
        event("P2", False, t - timedelta(minutes=5)),  # car parked before the period: ignored
        event("P1", True, t),
        event("P3", True, t + timedelta(minutes=10)),
        event("P1", False, t + timedelta(minutes=30)),  # P1 stayed 30 min
        event("P3", False, t + timedelta(minutes=100)),  # P3 stayed 90 min
        event("P4", True, t + timedelta(minutes=110)),  # still parked at the end: no duration
    ]

    out = await stats.summary(t - timedelta(minutes=10), t + timedelta(hours=3))

    assert out.entries == 3
    assert out.avg_duration_min == 60.0


async def test_summary_without_data(stats):
    out = await stats.summary(MONDAY_8H_UTC, MONDAY_8H_UTC + timedelta(days=1))

    assert out.samples == 0
    assert out.avg_rate is None
    assert out.avg_duration_min is None
    assert out.heatmap == []


async def test_date_without_time_zone_is_local_time(stats, history):
    history.snapshots.append(snap(MONDAY_8H_UTC, 1.0))  # 09:00 local

    out = await stats.occupancy(datetime(2026, 10, 12, 9, 0), datetime(2026, 10, 12, 10, 0), 60)

    assert len(out.points) == 1


# --- API ----------------------------------------------------------------------


def test_occupancy_endpoint_defaults_to_last_24_hours(client):
    body = client.get("/api/v1/stats/occupancy").json()

    start = datetime.fromisoformat(body["start"])
    end = datetime.fromisoformat(body["end"])
    assert end - start == timedelta(days=1)
    assert body["step_min"] == 15
    assert body["points"] == []


def test_occupancy_endpoint_accepts_from_and_to(client):
    response = client.get(
        "/api/v1/stats/occupancy",
        params={"from": "2026-10-12T00:00:00", "to": "2026-10-13T00:00:00", "step": 60},
    )
    assert response.status_code == 200
    assert response.json()["step_min"] == 60


@pytest.mark.parametrize(
    "params",
    [
        {"step": 7},  # doesn't divide a day
        {"from": "2026-10-13T00:00:00", "to": "2026-10-12T00:00:00"},  # reversed
        {"from": "2026-01-01T00:00:00", "to": "2026-10-12T00:00:00"},  # too long
        {"from": "yesterday"},
    ],
)
def test_occupancy_endpoint_rejects_bad_parameters(client, params):
    assert client.get("/api/v1/stats/occupancy", params=params).status_code == 422


def test_summary_endpoint(client):
    body = client.get("/api/v1/stats/summary").json()

    assert body["entries"] == 0
    assert body["timezone"] == "UTC"
