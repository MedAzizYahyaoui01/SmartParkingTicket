"""From the occupancy time series to a table of features, one row per moment `t`.

The series is the global occupancy rate on a regular 5-minute grid (UTC), with NaN where
nothing was recorded (sensors offline). For a horizon `h`, the row at `t` describes what is
known at `t` and the target is the rate at `t + h`:

- calendar of the *target* time `t + h` (local time): it is known in advance;
- cyclical sin/cos encodings, so 23:55 and 00:00 (or Sunday and Monday) are close;
- lags: the rate now and 5 / 15 / 30 / 60 min ago;
- the rate at the same time as the target, yesterday and last week (both in the past);
- rolling mean and standard deviation over the last 30 and 60 min (trend).

Nothing at `t` ever reads a value after `t`: `tests/test_ml.py` checks it by changing the
future and comparing the rows.

The grid step is a parameter: the live parking uses 5 minutes, the Birmingham benchmark
30 minutes. Lags and rolling windows that don't fit the step are left out.
"""

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.ml.calendar import is_holiday

STEP_MIN = 5
HORIZONS_MIN = (15, 30, 60, 120, 180)

LAGS_MIN = (5, 15, 30, 60)
ROLLING_MIN = (30, 60)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)

# The history needed before `t` to compute every feature
LOOKBACK = WEEK


def lags_for(step_min: int) -> list[int]:
    """Lags (minutes) that fall on the grid."""
    return [m for m in LAGS_MIN if m % step_min == 0]


def rolling_for(step_min: int) -> list[int]:
    """Rolling windows (minutes) of at least two points."""
    return [m for m in ROLLING_MIN if m >= 2 * step_min]


def feature_names(step_min: int = STEP_MIN) -> list[str]:
    return [
        "hour",
        "minute",
        "weekday",
        "is_weekend",
        "is_holiday",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
        "rate_now",
        *(f"lag_{m}" for m in lags_for(step_min)),
        "same_time_yesterday",
        "same_time_last_week",
        *(f"roll_{s}_{m}" for m in rolling_for(step_min) for s in ("mean", "std")),
    ]


FEATURES = feature_names(STEP_MIN)

# Short descriptions, for the feature importance chart on the dashboard
FEATURE_LABELS = {
    "hour": "Hour of the day",
    "minute": "Minute",
    "weekday": "Day of the week",
    "is_weekend": "Weekend",
    "is_holiday": "Public holiday",
    "hour_sin": "Hour (sin)",
    "hour_cos": "Hour (cos)",
    "weekday_sin": "Weekday (sin)",
    "weekday_cos": "Weekday (cos)",
    "rate_now": "Rate now",
    **{f"lag_{m}": f"Rate {m} min ago" for m in LAGS_MIN},
    "same_time_yesterday": "Same time yesterday",
    "same_time_last_week": "Same time last week",
    **{f"roll_mean_{m}": f"Mean, last {m} min" for m in ROLLING_MIN},
    **{f"roll_std_{m}": f"Std dev, last {m} min" for m in ROLLING_MIN},
}


def to_series(points: Iterable[dict[str, Any]], step_min: int = STEP_MIN) -> pd.Series:
    """[{ts, rate}] (any resolution) -> mean rate per `step_min` bucket on a regular UTC
    grid, NaN where there is no data."""
    frame = pd.DataFrame(list(points), columns=["ts", "rate"])
    if frame.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"), name="rate")
    index = pd.DatetimeIndex(pd.to_datetime(frame["ts"], utc=True))
    series = pd.Series(frame["rate"].to_numpy(dtype=float), index=index).sort_index()
    return series.resample(f"{step_min}min").mean().rename("rate")


def _steps(delta: timedelta, step_min: int) -> int:
    return int(delta / timedelta(minutes=step_min))


def build_features(
    series: pd.Series,
    horizon_min: int,
    tz: str,
    step_min: int = STEP_MIN,
    holidays: Callable[[date], bool] = is_holiday,
) -> tuple[pd.DataFrame, pd.Series]:
    """(X, y) for every `t` of the series; `y` is the rate at `t + horizon`, NaN when it is
    not known yet (the last rows) — these rows are what we predict from."""
    rate = series.asfreq(f"{step_min}min")
    h = _steps(timedelta(minutes=horizon_min), step_min)
    target_time = rate.index + pd.Timedelta(minutes=horizon_min)
    local = target_time.tz_convert(tz)

    hour_frac = local.hour + local.minute / 60
    X = pd.DataFrame(index=rate.index)
    X["hour"] = local.hour
    X["minute"] = local.minute
    X["weekday"] = local.day_of_week
    X["is_weekend"] = (local.day_of_week >= 5).astype(int)
    X["is_holiday"] = [int(holidays(d)) for d in local.date]
    X["hour_sin"] = np.sin(2 * np.pi * hour_frac / 24)
    X["hour_cos"] = np.cos(2 * np.pi * hour_frac / 24)
    X["weekday_sin"] = np.sin(2 * np.pi * local.day_of_week / 7)
    X["weekday_cos"] = np.cos(2 * np.pi * local.day_of_week / 7)

    X["rate_now"] = rate
    for m in lags_for(step_min):
        X[f"lag_{m}"] = rate.shift(_steps(timedelta(minutes=m), step_min))
    # Same time as the target, one day / one week earlier: t + h - 1 day is in the past
    X["same_time_yesterday"] = rate.shift(_steps(DAY, step_min) - h)
    X["same_time_last_week"] = rate.shift(_steps(WEEK, step_min) - h)
    for m in rolling_for(step_min):
        window = rate.rolling(_steps(timedelta(minutes=m), step_min), min_periods=1)
        X[f"roll_mean_{m}"] = window.mean()
        X[f"roll_std_{m}"] = window.std(ddof=0)

    y = rate.shift(-h).rename("target")
    return X[feature_names(step_min)], y
