"""Benchmark on real data: UCI "Parking Birmingham" (CC BY 4.0).

Our 4-spot parking is trained on synthetic history, so a good score there only proves the
model learned our own generator. This runs the *same* comparison (same features, models
and time-based split) on real car parks:

- 30 car parks run by Birmingham City Council, 4 Oct - 19 Dec 2016, 35,717 readings;
- one reading about every 30 minutes, only from 8:00 to 16:30;
- columns: SystemCodeNumber, Capacity, Occupancy, LastUpdated (local time).

So the grid step is 30 min (lags of 5 and 15 min don't exist), nights are gaps, and the
car parks are pooled into one dataset. The models trained here are only scored, never
used for the live parking. Source: https://archive.ics.uci.edu/dataset/482/parking+birmingham
"""

import io
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml.features import to_series
from app.ml.models import LABELS
from app.ml.train import evaluate

URL = "https://archive.ics.uci.edu/static/public/482/parking+birmingham.zip"
DEFAULT_PATH = Path("data/parking-birmingham.zip")
MAX_DOWNLOAD = 5_000_000  # the zip is ~240 KB

STEP_MIN = 30
HORIZONS_MIN = (30, 60, 120)
MIN_READINGS = 500  # two car parks have only a few days of data: left out


def download(path: Path = DEFAULT_PATH) -> Path:
    """Fetches the dataset once (kept in backend/data/, ignored by Git)."""
    if path.is_file():
        return path
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError(f"{URL} is larger than expected, not saved")
    zipfile.ZipFile(io.BytesIO(data)).getinfo("dataset.csv")  # it is the expected archive
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def read(path: Path) -> pd.DataFrame:
    """The raw readings, from the UCI zip or an extracted CSV."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive, archive.open("dataset.csv") as f:
            return pd.read_csv(f, parse_dates=["LastUpdated"])
    return pd.read_csv(path, parse_dates=["LastUpdated"])


def car_park_series(readings: pd.DataFrame) -> dict[str, pd.Series]:
    """One occupancy-rate series per car park, on a 30-min grid.

    Readings come at about :00 and :30 (e.g. 07:59:42, 08:25:47), so they are rounded to the
    nearest half hour. A few counts exceed the capacity or go below 0 (sensor drift): the
    rate is clipped to 0..1. Times are local wall-clock times; they are kept as such (read as
    UTC), so the hour features are local hours, across the October clock change too.
    """
    df = readings.assign(
        rate=(readings["Occupancy"] / readings["Capacity"]).clip(0, 1),
        ts=readings["LastUpdated"].dt.round(f"{STEP_MIN}min"),
    )
    counts = df["SystemCodeNumber"].value_counts()
    keep = counts[counts >= MIN_READINGS].index
    return {
        name: to_series(group[["ts", "rate"]].to_dict("records"), STEP_MIN)
        for name, group in df[df["SystemCodeNumber"].isin(keep)].groupby("SystemCodeNumber")
    }


def benchmark(path: Path, fast: bool = False, seed: int = 42) -> dict[str, Any]:
    """The model comparison on the Birmingham car parks (scores only)."""
    parks = car_park_series(read(path))
    ev = evaluate(
        list(parks.values()),
        "UTC",
        HORIZONS_MIN,
        step_min=STEP_MIN,
        holidays=lambda day: False,  # no UK bank holiday between 4 Oct and 19 Dec 2016
        fast=fast,
        seed=seed,
    )
    return {
        "name": "birmingham",
        "title": "Birmingham car parks (UCI, 2016)",
        "source": f"UCI Parking Birmingham, {len(parks)} car parks, readings every 30 min "
        "from 8:00 to 16:30 (CC BY 4.0)",
        "url": "https://archive.ics.uci.edu/dataset/482/parking+birmingham",
        "best": ev["best"],
        "best_label": LABELS[ev["best"]],
        "step_min": STEP_MIN,
        "horizons": ev["horizons"],
        "data": ev["data"],
        "mean_mae": ev["mean_mae"],
        "results": ev["results"],
        "importance": ev["importance"],
    }
