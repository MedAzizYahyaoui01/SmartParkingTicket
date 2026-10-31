"""The four models compared on the same data.

| Key      | Model                              | Role                                         |
|----------|------------------------------------|----------------------------------------------|
| naive    | Same time last week                | The bar to beat                              |
| linear   | Linear regression on lags (ridge)  | Classic, interpretable time-series approach  |
| rf       | Random Forest (scikit-learn)       | Robust non-linear model, little tuning       |
| xgboost  | XGBoost (gradient boosting)        | Usually the most accurate on tabular data    |

One model is trained per horizon (15, 30, 60 min...): the "direct" strategy, simpler and
more robust than feeding a model its own predictions.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor


class SameTimeLastWeek(RegressorMixin, BaseEstimator):
    """Predicts the rate seen at the same time one week earlier. Nothing to learn."""

    def fit(self, X: pd.DataFrame, y: Any = None) -> "SameTimeLastWeek":
        self.is_fitted_ = True
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X["same_time_last_week"].to_numpy(dtype=float)


LABELS = {
    "naive": "Naive (same time last week)",
    "linear": "Linear regression on lags",
    "rf": "Random Forest",
    "xgboost": "XGBoost",
}


def candidates(fast: bool = False, seed: int = 42) -> dict[str, Callable[[], Any]]:
    """Factories of untrained models. `fast` shrinks the ensembles (tests)."""
    return {
        "naive": SameTimeLastWeek,
        "linear": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "rf": lambda: RandomForestRegressor(
            n_estimators=30 if fast else 150,
            # Large leaves average out the noise of a 4-spot rate (only 5 possible values)
            min_samples_leaf=30,
            max_features=0.5,
            n_jobs=-1,
            random_state=seed,
        ),
        "xgboost": lambda: XGBRegressor(
            n_estimators=60 if fast else 500,
            learning_rate=0.1 if fast else 0.05,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            tree_method="hist",
            n_jobs=-1,
            random_state=seed,
        ),
    }


# Small grids for `train --tune` (TimeSeriesSplit cross-validation on the training part)
PARAM_GRIDS = {
    "rf": {"min_samples_leaf": [10, 30, 60], "max_features": [0.33, 0.5, 1.0]},
    "xgboost": {"max_depth": [4, 6, 8], "learning_rate": [0.03, 0.05, 0.1]},
}


def feature_importance(model: Any, features: list[str]) -> dict[str, float] | None:
    """Built-in importance of the tree models (None for the others)."""
    values = getattr(model, "feature_importances_", None)
    if values is None:
        return None
    total = float(np.sum(values)) or 1.0
    return {f: float(v) / total for f, v in zip(features, values, strict=True)}
