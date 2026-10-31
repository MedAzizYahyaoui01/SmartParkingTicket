"""Synthetic parking history: what the API would have recorded over N days.

Used by `tools/seed_history.py` (to fill MongoDB) and by the trainer (to train without a
database). Standard library only, so the seeding script needs nothing but pymongo.

Daily pattern (local time): quiet nights, a morning peak around 9:00, the busiest time at
lunch, a quieter afternoon; weekends and public holidays are calmer and peak around midday.
Each spot is a small random process: a free spot gets a car with some probability per
minute, a parked car leaves after ~45-90 min on average. The arrival probability is set so
the average occupancy follows the daily pattern, so the data is noisy, like real data.
"""

import math
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.ml.calendar import is_holiday

SPOTS = ["P1", "P2", "P3", "P4"]


def _bump(hour: float, center: float, width: float, height: float) -> float:
    return height * math.exp(-(((hour - center) / width) ** 2))


def target_rate(local: datetime) -> float:
    """Expected occupancy rate (0..1) at this local time."""
    h = local.hour + local.minute / 60
    if local.weekday() < 5 and not is_holiday(local.date()):  # working day
        rate = 0.08 + _bump(h, 9, 1.5, 0.6) + _bump(h, 12.75, 1.3, 0.8) + _bump(h, 17, 2, 0.35)
    else:
        rate = 0.05 + _bump(h, 12.5, 3, 0.55)
    return min(rate, 0.95)


def mean_stay_min(local: datetime) -> float:
    """Average parking time: short visits at lunch, longer in the morning and evening."""
    return 45 if 11 <= local.hour < 15 else 90


def simulate(
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    rng: random.Random,
    spots: list[str] = SPOTS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(snapshots, events) for the period, minute by minute, tagged `synthetic: true`."""
    occupied = {s: False for s in spots}
    snapshots, events = [], []
    t = start
    while t < end:
        local = t.astimezone(tz)
        p = target_rate(local)
        leave = 1 / mean_stay_min(local)
        # Steady state of a free<->occupied process: p = arrive / (arrive + leave)
        arrive = min(leave * p / (1 - p), 1.0)

        for spot in spots:
            change = rng.random() < (leave if occupied[spot] else arrive)
            if change:
                occupied[spot] = not occupied[spot]
                events.append(
                    {
                        "spot_id": spot,
                        "occupied": occupied[spot],
                        "distance_cm": round(rng.uniform(10, 40), 1) if occupied[spot] else 400.0,
                        "ts": t + timedelta(seconds=rng.randint(0, 59)),
                        "synthetic": True,
                    }
                )

        n = sum(occupied.values())
        snapshots.append(
            {
                "ts": t,
                "occupied": n,
                "total": len(spots),
                "rate": n / len(spots),
                "synthetic": True,
            }
        )
        t += timedelta(minutes=1)
    return snapshots, events
