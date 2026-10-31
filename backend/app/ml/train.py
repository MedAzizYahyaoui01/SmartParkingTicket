"""Trains and compares the occupancy models, then saves the best one.

    python -m app.ml.train                       # history from MongoDB (synthetic + live)
    python -m app.ml.train --source synthetic    # 90 synthetic days, no database needed
    python -m app.ml.train --tune                # + hyper-parameter search (slower)

Protocol: time-based split, never random — every model is trained on the first 80% of the
timeline and scored on the last 20% (a random split would leak the future into training).
Metrics: MAE (main), RMSE, R², training and prediction time. The model family with the
lowest average MAE over the horizons is saved with joblib, with the whole comparison, so
the API can serve both predictions and the comparison table.
"""

import argparse
import random
import time
from datetime import UTC, datetime, timedelta
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
from app.ml.features import FEATURES, HORIZONS_MIN, STEP_MIN, build_features, to_series
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


def train(
    series: pd.Series,
    tz: str,
    horizons: tuple[int, ...] = HORIZONS_MIN,
    source: str = "",
    fast: bool = False,
    tune: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Trains every candidate for every horizon; returns the artifact to save."""
    series = series.asfreq(f"{STEP_MIN}min")
    known = series.dropna()
    if known.empty:
        raise ValueError("no occupancy history to learn from")
    start, end = known.index[0], known.index[-1]
    cutoff = start + (end - start) * TRAIN_SHARE

    results: list[dict[str, Any]] = []
    fitted: dict[str, dict[int, Any]] = {key: {} for key in LABELS}
    importances: dict[str, list[dict[str, float]]] = {}

    for horizon in horizons:
        X, y = build_features(series, horizon, tz)
        usable = X.notna().all(axis=1) & y.notna()
        target_time = X.index + pd.Timedelta(minutes=horizon)
        # A training row's target must be before the cutoff, so no test value is ever seen
        train_rows = usable & (target_time < cutoff)
        test_rows = usable & (X.index >= cutoff)
        if train_rows.sum() < MIN_TRAIN_ROWS or test_rows.sum() == 0:
            raise ValueError(
                f"not enough history: {int(train_rows.sum())} training rows for the "
                f"{horizon}-min horizon, at least {MIN_TRAIN_ROWS} needed (about 10 days "
                "of data, since a feature looks one week back)"
            )
        X_train, y_train = X[train_rows], y[train_rows]
        X_test, y_test = X[test_rows], y[test_rows]

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
                    "train_rows": int(train_rows.sum()),
                    "test_rows": int(test_rows.sum()),
                }
            )
            importance = feature_importance(model, FEATURES)
            if importance:
                importances.setdefault(key, []).append(importance)

    mean_mae = {
        key: float(np.mean([r["mae"] for r in results if r["model"] == key])) for key in LABELS
    }
    best = min(mean_mae, key=mean_mae.get)
    return {
        "version": ARTIFACT_VERSION,
        "model": best,
        "label": LABELS[best],
        "models": fitted[best],
        "features": FEATURES,
        "step_min": STEP_MIN,
        "horizons": list(horizons),
        "timezone": tz,
        "trained_at": datetime.now(UTC),
        "data": {
            "source": source,
            "start": start.to_pydatetime(),
            "end": end.to_pydatetime(),
            "points": int(known.size),
            "train_until": cutoff.to_pydatetime(),
        },
        "mean_mae": mean_mae,
        "results": results,
        # Averaged over the horizons, largest first
        "importance": {
            key: dict(
                sorted(
                    ((f, float(np.mean([imp[f] for imp in values]))) for f in FEATURES),
                    key=lambda item: item[1],
                    reverse=True,
                )
            )
            for key, values in importances.items()
        },
    }


def save(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    joblib.dump(artifact, tmp, compress=3)
    tmp.replace(path)  # atomic: the API never loads a half-written file


def print_report(artifact: dict[str, Any]) -> None:
    print(f"\n{'Model':<30} {'Horizon':>8} {'MAE':>7} {'RMSE':>7} {'R2':>7} {'Fit (s)':>8}")
    for r in artifact["results"]:
        print(
            f"{r['label']:<30} {r['horizon_min']:>5} min {r['mae']:>7.4f} {r['rmse']:>7.4f} "
            f"{r['r2']:>7.3f} {r['fit_s']:>8.2f}"
        )
    print("\nAverage MAE: " + ", ".join(f"{k} {v:.4f}" for k, v in artifact["mean_mae"].items()))
    print(f"Best model: {artifact['label']}")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", choices=["mongo", "synthetic"], default="mongo")
    parser.add_argument("--days", type=int, default=90, help="synthetic days (default 90)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tune", action="store_true", help="TimeSeriesSplit grid search")
    parser.add_argument("--fast", action="store_true", help="small ensembles (quick check)")
    parser.add_argument("--output", type=Path, default=Path(settings.model_path))
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
    print_report(artifact)
    save(artifact, args.output)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
