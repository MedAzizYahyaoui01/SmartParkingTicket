"""Predicted occupancy for the next hours, from the trained model and the recent history."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.ml.features import FEATURE_LABELS, LOOKBACK, build_features, to_series
from app.ml.predictor import ModelStore
from app.repositories.history import HistoryRepository
from app.schemas.predictions import (
    BenchmarkOut,
    DataPeriod,
    FeatureImportance,
    ModelResult,
    ModelsCompareOut,
    PredictionPoint,
    PredictionsOut,
    TrainingData,
)

logger = logging.getLogger(__name__)

# Older than this, the latest data no longer describes "now" (sensors offline)
STALE_AFTER = timedelta(minutes=15)
# Extra history read beyond the one-week lookback, to find a complete row despite gaps
MARGIN = timedelta(hours=6)


class ModelNotReadyError(Exception):
    """No model has been trained yet."""


class NotEnoughHistoryError(Exception):
    """The recent history doesn't cover the week the features look back on."""


class PredictionService:
    def __init__(
        self,
        history: HistoryRepository,
        models: ModelStore,
        total_spots: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.history = history
        self.models = models
        self.total_spots = total_spots
        self.now = now
        # Same model + same latest bucket = same answer: computed (and logged) once
        self._cache: tuple[Any, ...] | None = None

    def _artifact(self) -> dict[str, Any]:
        artifact = self.models.get()
        if artifact is None:
            raise ModelNotReadyError(
                "No prediction model yet: train one with `python -m app.ml.train`"
            )
        return artifact

    def _point(self, horizon_min: int, ts: datetime, rate: float) -> PredictionPoint:
        rate = round(float(np.clip(rate, 0.0, 1.0)), 4)
        return PredictionPoint(
            horizon_min=horizon_min,
            ts=ts,
            rate=rate,
            free_spots=round(self.total_spots * (1 - rate)),
        )

    async def predict(self, horizon_min: int) -> PredictionsOut:
        artifact = self._artifact()
        horizons = [h for h in artifact["horizons"] if h <= horizon_min]
        if not horizons:
            raise ValueError(f"the shortest horizon is {artifact['horizons'][0]} min")

        tz, step = artifact["timezone"], artifact["step_min"]
        now = self.now()
        rows = await self.history.occupancy_series(now - LOOKBACK - MARGIN, now, step, tz)
        series = to_series(rows, step)
        known = series.dropna()
        if not known.empty and now - known.index[-1] > MARGIN:
            raise NotEnoughHistoryError(
                f"No occupancy data since {known.index[-1]:%Y-%m-%d %H:%M} UTC: the sensors "
                "seem offline, so there is no recent state to predict from"
            )

        # The latest moment where the features of every horizon are complete
        features = {}
        complete = None
        for h in horizons:
            X, _ = build_features(series, h, tz, step)
            features[h] = X
            ok = X.index[X.notna().all(axis=1)]
            complete = ok if complete is None else complete.intersection(ok)
        if complete is None or complete.empty:
            raise NotEnoughHistoryError(
                "Not enough recent history to predict: the model needs the last 7 days "
                "(seed it with tools/seed_history.py, or let the sensors run)"
            )
        base = complete[-1]

        key = (artifact["trained_at"], base, tuple(horizons))
        if self._cache and self._cache[0] == key:
            predicted = self._cache[1]
        else:
            predicted = {
                h: float(artifact["models"][h].predict(features[h].loc[[base]])[0])
                for h in horizons
            }
            self._cache = (key, predicted)
            await self._log(artifact["model"], base, predicted)

        based_on = base.to_pydatetime()
        current = self._point(0, based_on, float(series[base]))
        points = [
            self._point(h, based_on + timedelta(minutes=h), rate) for h, rate in predicted.items()
        ]
        return PredictionsOut(
            model=artifact["model"],
            label=artifact["label"],
            trained_at=artifact["trained_at"],
            based_on=based_on,
            stale=now - based_on > STALE_AFTER,
            total_spots=self.total_spots,
            current=current,
            points=points,
            best=min([current, *points], key=lambda p: p.rate),  # earliest wins a tie
        )

    async def _log(self, model: str, base: pd.Timestamp, predicted: dict[int, float]) -> None:
        """Stores each prediction served, to compare it later with what really happened."""
        made_at = base.to_pydatetime()
        docs = [
            {
                "model": model,
                "horizon_min": h,
                "predicted_rate": round(float(np.clip(rate, 0.0, 1.0)), 4),
                "ts": made_at + timedelta(minutes=h),  # the time predicted
                "made_at": made_at,
            }
            for h, rate in predicted.items()
        ]
        try:
            await self.history.insert_predictions(docs)
        except Exception:
            logger.warning("Could not store the predictions", exc_info=True)

    def compare(self) -> ModelsCompareOut:
        artifact = self._artifact()
        return ModelsCompareOut(
            best_model=artifact["model"],
            label=artifact["label"],
            trained_at=artifact["trained_at"],
            timezone=artifact["timezone"],
            horizons=artifact["horizons"],
            data=TrainingData(**artifact["data"]),
            mean_mae=artifact["mean_mae"],
            results=[ModelResult(**r) for r in artifact["results"]],
            feature_importance=_importance(artifact["importance"]),
            benchmarks=[
                BenchmarkOut(
                    name=b["name"],
                    title=b["title"],
                    source=b["source"],
                    url=b["url"],
                    best_model=b["best"],
                    label=b["best_label"],
                    step_min=b["step_min"],
                    horizons=b["horizons"],
                    data=DataPeriod(**b["data"]),
                    mean_mae=b["mean_mae"],
                    results=[ModelResult(**r) for r in b["results"]],
                    feature_importance=_importance(b["importance"]),
                )
                for b in artifact.get("benchmarks", {}).values()
            ],
        )


def _importance(by_model: dict[str, dict[str, float]]) -> dict[str, list[FeatureImportance]]:
    return {
        model: [
            FeatureImportance(feature=f, label=FEATURE_LABELS.get(f, f), importance=round(v, 4))
            for f, v in values.items()
        ]
        for model, values in by_model.items()
    }
