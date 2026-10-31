"""Trains and compares the occupancy models, then saves the best one.

    python -m app.ml.train                       # history from MongoDB (synthetic + live)
    python -m app.ml.train --source synthetic    # 90 synthetic days, no database needed
    python -m app.ml.train --tune                # + hyper-parameter search (slower)
    python -m app.ml.train --birmingham          # + the same comparison on real car parks

Protocol: time-based split, never random — every model is trained on the first 80% of the
timeline and scored on the last 20% (a random split would leak the future into training).
Metrics: MAE (main), RMSE, R², training and prediction time. The model family with the
lowest average MAE over the horizons is saved with joblib, with the whole comparison, so
the API can serve both predictions and the comparison table.
"""

import argparse
import random
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from pymongo import MongoClient
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from app.config import get_settings
from app.ml.calendar import is_holiday
from app.ml.features import HORIZONS_MIN, STEP_MIN, build_features, feature_names, to_series
from app.ml.models import LABELS, PARAM_GRIDS, candidates, feature_importance
from app.ml.synthetic import simulate

ARTIFACT_VERSION = 1
TRAIN_SHARE = 0.8
MIN_TRAIN_ROWS = 2 * 24 * 60 // STEP_MIN  # two days of usable rows


def synthetic_series(days: int, tz: str, seed: int = 42) -> pd.Series:
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    snapshots, _ = simulate(end - timedelta(days=days), end, ZoneInfo(tz), random.Random(seed))
    return to_series(snapshots)


def mongo_series(uri: str, db_name: str) -> pd.Series:
    """Every snapshot in MongoDB (synthetic and live), averaged per 5 minutes."""
    client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    try:
        bucket = {"$dateTrunc": {"date": "$ts", "unit": "minute", "binSize": STEP_MIN}}
        pipeline = [
            {"$group": {"_id": bucket, "rate": {"$avg": "$rate"}}},
            {"$sort": {"_id": 1}},
        ]
        rows = client[db_name]["occupancy_snapshots"].aggregate(pipeline)
        return to_series({"ts": r["_id"], "rate": r["rate"]} for r in rows)
    finally:
        client.close()


def _fit(key: str, model: Any, X: pd.DataFrame, y: pd.Series, tune: bool) -> Any:
    if tune and key in PARAM_GRIDS:
        search = GridSearchCV(
            model,
            PARAM_GRIDS[key],
            cv=TimeSeriesSplit(n_splits=5),
            scoring="neg_mean_absolute_error",
        )
        return search.fit(X, y).best_estimator_
    return model.fit(X, y)


def evaluate(
    series: list[pd.Series],
    tz: str,
    horizons: tuple[int, ...],
    step_min: int = STEP_MIN,
    holidays: Callable[[date], bool] = is_holiday,
    fast: bool = False,
    tune: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Trains and scores every candidate for every horizon on one or more series (e.g. one
    per car park, pooled into one dataset), with the same time-based split for all."""
    series = [s.asfreq(f"{step_min}min") for s in series]
    known = [s.dropna() for s in series if s.notna().any()]
    if not known:
        raise ValueError("no occupancy history to learn from")
    start = min(k.index[0] for k in known)
    end = max(k.index[-1] for k in known)
    cutoff = start + (end - start) * TRAIN_SHARE
    features = feature_names(step_min)

    results: list[dict[str, Any]] = []
    fitted: dict[str, dict[int, Any]] = {key: {} for key in LABELS}
    importances: dict[str, list[dict[str, float]]] = {}

    for horizon in horizons:
        train_parts, test_parts = [], []
        for s in series:
            X, y = build_features(s, horizon, tz, step_min, holidays)
            usable = X.notna().all(axis=1) & y.notna()
            target_time = X.index + pd.Timedelta(minutes=horizon)
            # A training row's target must be before the cutoff, so no test value is seen
            train_parts.append(
                (X[usable & (target_time < cutoff)], y[usable & (target_time < cutoff)])
            )
            test_parts.append((X[usable & (X.index >= cutoff)], y[usable & (X.index >= cutoff)]))
        # Pooled rows in time order (TimeSeriesSplit relies on it when tuning)
        X_train = pd.concat([x for x, _ in train_parts]).sort_index(kind="stable")
        y_train = pd.concat([y for _, y in train_parts]).sort_index(kind="stable")
        X_test = pd.concat([x for x, _ in test_parts])
        y_test = pd.concat([y for _, y in test_parts])
        if len(X_train) < MIN_TRAIN_ROWS or len(X_test) == 0:
            raise ValueError(
                f"not enough history: {len(X_train)} training rows for the "
                f"{horizon}-min horizon, at least {MIN_TRAIN_ROWS} needed (about 10 days "
                "of data, since a feature looks one week back)"
            )

        for key, factory in candidates(fast, seed).items():
            t0 = time.perf_counter()
            model = _fit(key, factory(), X_train, y_train, tune)
            fit_s = time.perf_counter() - t0
            t0 = time.perf_counter()
            predicted = np.clip(model.predict(X_test), 0.0, 1.0)
            predict_s = time.perf_counter() - t0

            fitted[key][horizon] = model
            results.append(
                {
                    "model": key,
                    "label": LABELS[key],
                    "horizon_min": horizon,
                    "mae": float(mean_absolute_error(y_test, predicted)),
                    "rmse": float(np.sqrt(mean_squared_error(y_test, predicted))),
                    "r2": float(r2_score(y_test, predicted)),
                    "fit_s": round(fit_s, 3),
                    "predict_s": round(predict_s, 4),
                    "train_rows": len(X_train),
                    "test_rows": len(X_test),
                }
            )
            importance = feature_importance(model, features)
            if importance:
                importances.setdefault(key, []).append(importance)

    mean_mae = {
        key: float(np.mean([r["mae"] for r in results if r["model"] == key])) for key in LABELS
    }
    return {
        "best": min(mean_mae, key=mean_mae.get),
        "fitted": fitted,
        "features": features,
        "step_min": step_min,
        "horizons": list(horizons),
        "data": {
            "start": start.to_pydatetime(),
            "end": end.to_pydatetime(),
            "points": int(sum(k.size for k in known)),
            "train_until": cutoff.to_pydatetime(),
        },
        "mean_mae": mean_mae,
        "results": results,
        # Averaged over the horizons, largest first
        "importance": {
            key: dict(
                sorted(
                    ((f, float(np.mean([imp[f] for imp in values]))) for f in features),
                    key=lambda item: item[1],
                    reverse=True,
                )
            )
            for key, values in importances.items()
        },
    }


def train(
    series: pd.Series,
    tz: str,
    horizons: tuple[int, ...] = HORIZONS_MIN,
    source: str = "",
    fast: bool = False,
    tune: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Trains every candidate for every horizon; returns the artifact to save (the best
    model family, with the whole comparison)."""
    ev = evaluate([series], tz, horizons, fast=fast, tune=tune, seed=seed)
    best = ev["best"]
    return {
        "version": ARTIFACT_VERSION,
        "model": best,
        "label": LABELS[best],
        "models": ev["fitted"][best],
        "features": ev["features"],
        "step_min": ev["step_min"],
        "horizons": ev["horizons"],
        "timezone": tz,
        "trained_at": datetime.now(UTC),
        "data": {"source": source, **ev["data"]},
        "mean_mae": ev["mean_mae"],
        "results": ev["results"],
        "importance": ev["importance"],
        "benchmarks": {},  # the same comparison on other datasets (see birmingham.py)
    }


def save(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    joblib.dump(artifact, tmp, compress=3)
    tmp.replace(path)  # atomic: the API never loads a half-written file


def print_report(artifact: dict[str, Any], title: str = "") -> None:
    if title:
        print(f"\n{title}")
    print(f"\n{'Model':<30} {'Horizon':>8} {'MAE':>7} {'RMSE':>7} {'R2':>7} {'Fit (s)':>8}")
    for r in artifact["results"]:
        print(
            f"{r['label']:<30} {r['horizon_min']:>5} min {r['mae']:>7.4f} {r['rmse']:>7.4f} "
            f"{r['r2']:>7.3f} {r['fit_s']:>8.2f}"
        )
    print("\nAverage MAE: " + ", ".join(f"{k} {v:.4f}" for k, v in artifact["mean_mae"].items()))
    print(f"Best model: {artifact.get('label') or artifact.get('best_label')}")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", choices=["mongo", "synthetic"], default="mongo")
    parser.add_argument("--days", type=int, default=90, help="synthetic days (default 90)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tune", action="store_true", help="TimeSeriesSplit grid search")
    parser.add_argument("--fast", action="store_true", help="small ensembles (quick check)")
    parser.add_argument("--output", type=Path, default=Path(settings.model_path))
    parser.add_argument(
        "--birmingham",
        nargs="?",
        type=Path,
        const=Path("data/parking-birmingham.zip"),
        metavar="PATH",
        help="also run the comparison on the real UCI Birmingham car parks "
        "(downloaded to PATH the first time, ~240 KB)",
    )
    args = parser.parse_args()

    if args.source == "synthetic":
        series = synthetic_series(args.days, settings.timezone, args.seed)
        source = f"synthetic ({args.days} days)"
    else:
        series = mongo_series(settings.mongo_uri, settings.mongo_db)
        source = "MongoDB"
    print(f"{series.notna().sum()} points of {STEP_MIN} min from {source}, training...")

    artifact = train(
        series,
        settings.timezone,
        source=source,
        fast=args.fast,
        tune=args.tune,
        seed=args.seed,
    )
    print_report(artifact, f"Our parking ({source})")

    if args.birmingham:
        from app.ml import birmingham  # imports this module: loaded only when asked

        path = birmingham.download(args.birmingham)
        print(f"\nBenchmark on real data: {path}...")
        bench = birmingham.benchmark(path, fast=args.fast, seed=args.seed)
        artifact["benchmarks"]["birmingham"] = bench
        print_report(bench, bench["source"])

    save(artifact, args.output)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
