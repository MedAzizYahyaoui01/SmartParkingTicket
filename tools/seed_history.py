"""Fills MongoDB with realistic synthetic parking history.

A live demo only has a few minutes of data; the statistics page and the AI need
weeks. This script simulates the 4 spots minute by minute over the past N days and writes
exactly what the API would have written: one snapshot per minute in `occupancy_snapshots`
and one event per state change in `occupancy_events`.

The simulation itself (daily pattern, random arrivals and departures) is in
`backend/app/ml/synthetic.py`, shared with the trainer; it needs only the standard library.

Every document is tagged `synthetic: true`, so it can be told apart from (or removed
without touching) real ESP32 data:

    python tools/seed_history.py --days 28
    python tools/seed_history.py --clear        # remove the synthetic data only
"""

import argparse
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pymongo import MongoClient

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.synthetic import simulate  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE lines), so the script needs only pymongo."""
    env = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def main() -> None:
    env = load_env(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=28, help="days of history (default 28)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (same seed = same data)")
    parser.add_argument("--clear", action="store_true", help="only delete the synthetic data")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGO_URI") or env.get("MONGO_URI"))
    parser.add_argument(
        "--db",
        default=os.environ.get("MONGO_DB") or env.get("MONGO_DB", "smart_parking"),
    )
    parser.add_argument(
        "--timezone", default=os.environ.get("TIMEZONE") or env.get("TIMEZONE", "UTC")
    )
    args = parser.parse_args()
    if not args.mongo_uri:
        parser.error("no MongoDB URI: set MONGO_URI in .env or pass --mongo-uri")

    db = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=3000, tz_aware=True)[args.db]

    # Always start clean, so running the script twice doesn't double the data
    removed_s = db.occupancy_snapshots.delete_many({"synthetic": True}).deleted_count
    removed_e = db.occupancy_events.delete_many({"synthetic": True}).deleted_count
    print(f"Removed {removed_s} synthetic snapshots and {removed_e} synthetic events")
    if args.clear:
        return

    if "occupancy_snapshots" not in db.list_collection_names():
        # Same time-series collection the API creates at start-up
        db.create_collection(
            "occupancy_snapshots",
            timeseries={"timeField": "ts", "granularity": "minutes"},
        )

    # Stop at the first real data (if any), so synthetic and live data never overlap
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    first_real = db.occupancy_snapshots.find_one({"synthetic": {"$ne": True}}, sort=[("ts", 1)])
    if first_real:
        end = min(end, first_real["ts"])
    start = end - timedelta(days=args.days)

    print(
        f"Simulating {args.days} days ({start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} UTC), "
        f"time zone {args.timezone}..."
    )
    snapshots, events = simulate(start, end, ZoneInfo(args.timezone), random.Random(args.seed))
    db.occupancy_snapshots.insert_many(snapshots, ordered=False)
    if events:
        db.occupancy_events.insert_many(events, ordered=False)

    avg = sum(s["rate"] for s in snapshots) / len(snapshots)
    entries = sum(1 for e in events if e["occupied"])
    print(
        f"Inserted {len(snapshots)} snapshots and {len(events)} events "
        f"({entries} entries, average occupancy {avg:.0%})"
    )


if __name__ == "__main__":
    main()
