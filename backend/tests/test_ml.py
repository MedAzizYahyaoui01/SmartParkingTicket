"""AI module: features, training protocol, model loading, and the prediction endpoints."""

import os
import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ml.calendar import is_holiday
from app.ml.features import FEATURES, build_features, to_series
from app.ml.predictor import ModelStore
from app.ml.synthetic import simulate
from app.ml.train import save, synthetic_series, train

HORIZONS = (15, 60)


@pytest.fixture(scope="module")
def artifact():
    """A quick model (small ensembles, 21 synthetic days), trained once for the module."""
    return train(synthetic_series(21, "UTC"), "UTC", horizons=HORIZONS, fast=True)


@pytest.fixture(scope="module")
def model_file(artifact, tmp_path_factory):
    path = tmp_path_factory.mktemp("models") / "best_model.joblib"
    save(artifact, path)
    return path


def _series(days: int = 10) -> pd.Series:
    rng = np.random.default_rng(0)
    index = pd.date_range("2026-10-01", periods=days * 288, freq="5min", tz="UTC")
    return pd.Series(rng.integers(0, 5, len(index)) / 4, index=index, name="rate")


# ------------------------------------------------------------------------ features


def test_features_never_read_the_future():
    series = _series()
    t = series.index[-500]
    X_before, _ = build_features(series, 60, "UTC")

    changed = series.copy()
    changed[changed.index > t] = 1 - changed[changed.index > t]  # rewrite the future
    X_after, y_after = build_features(changed, 60, "UTC")

    pd.testing.assert_frame_equal(X_before.loc[:t], X_after.loc[:t])
    assert y_after[t] == changed[t + pd.Timedelta(minutes=60)]  # only the target moved


def test_lags_point_at_the_right_times():
    series = _series()
    X, y = build_features(series, 60, "UTC")
    t = series.index[-100]
    h = pd.Timedelta(minutes=60)

    assert X.loc[t, "rate_now"] == series[t]
    assert X.loc[t, "lag_15"] == series[t - pd.Timedelta(minutes=15)]
    assert X.loc[t, "same_time_yesterday"] == series[t + h - pd.Timedelta(days=1)]
    assert X.loc[t, "same_time_last_week"] == series[t + h - pd.Timedelta(days=7)]
    assert y[t] == series[t + h]
    assert np.isnan(y.iloc[-1])  # the future of the last row is unknown
    assert list(X.columns) == FEATURES


def test_calendar_features_describe_the_target_time_in_local_time():
    index = pd.DatetimeIndex([datetime(2026, 10, 30, 22, 0, tzinfo=UTC)])  # Friday
    X, _ = build_features(pd.Series([0.5], index=index), 120, "Africa/Tunis")

    # 22:00 UTC + 2 h = 00:00 UTC = 01:00 in Tunis, on Saturday
    assert X.iloc[0]["hour"] == 1
    assert X.iloc[0]["weekday"] == 5
    assert X.iloc[0]["is_weekend"] == 1


def test_cyclical_encoding_keeps_midnight_close_to_23h55():
    index = pd.date_range("2026-10-05 23:40", periods=4, freq="5min", tz="UTC")
    X, _ = build_features(pd.Series(0.5, index=index), 15, "UTC")
    before, after = X.iloc[0], X.iloc[1]  # targets 23:55 and 00:00

    gap = np.hypot(before.hour_sin - after.hour_sin, before.hour_cos - after.hour_cos)
    assert gap < 0.05
    assert abs(before.hour - after.hour) == 23  # the plain number hides it


def test_holidays():
    assert is_holiday(date(2026, 3, 20))
    assert not is_holiday(date(2026, 3, 21))


def test_to_series_averages_per_5_minutes_and_keeps_gaps():
    start = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    points = [
        {"ts": start + timedelta(minutes=m), "rate": 0.5 if m < 3 else 1.0} for m in (0, 1, 2, 3, 4)
    ]
    points.append({"ts": start + timedelta(minutes=20), "rate": 0.25})

    series = to_series(points)

    assert series.iloc[0] == pytest.approx(0.7)
    assert series.isna().sum() == 3  # 08:05, 08:10, 08:15: no data, not invented
    assert series.iloc[-1] == 0.25


def test_holidays_are_quiet_in_the_synthetic_data():
    def daily_rate(day: datetime) -> float:
        snaps, _ = simulate(day, day + timedelta(days=1), ZoneInfo("UTC"), random.Random(1))
        return float(np.mean([s["rate"] for s in snaps]))

    holiday = datetime(2026, 10, 15, tzinfo=UTC)  # Thursday, Evacuation Day
    workday = datetime(2026, 10, 22, tzinfo=UTC)  # the next Thursday
    assert daily_rate(holiday) < daily_rate(workday)


# ------------------------------------------------------------------------ training


def test_every_model_is_evaluated_on_every_horizon(artifact):
    pairs = {(r["model"], r["horizon_min"]) for r in artifact["results"]}
    assert pairs == {(m, h) for m in ("naive", "linear", "rf", "xgboost") for h in HORIZONS}
    assert set(artifact["models"]) == set(HORIZONS)


def test_models_beat_the_naive_baseline(artifact):
    mae = artifact["mean_mae"]
    assert artifact["model"] != "naive"
    for model in ("linear", "rf", "xgboost"):
        assert mae[model] < mae["naive"], model


def test_split_is_time_based(artifact):
    data = artifact["data"]
    share = (data["train_until"] - data["start"]) / (data["end"] - data["start"])
    assert share == pytest.approx(0.8)
    assert all(r["train_rows"] > 0 and r["test_rows"] > 0 for r in artifact["results"])


def test_predictions_stay_within_0_and_1(artifact):
    X, _ = build_features(synthetic_series(10, "UTC", seed=7), 60, "UTC")
    X = X.dropna()
    predicted = np.clip(artifact["models"][60].predict(X), 0, 1)
    assert predicted.min() >= 0 and predicted.max() <= 1
    assert 0.05 < predicted.mean() < 0.9  # and they are not degenerate


def test_feature_importance_for_the_tree_models(artifact):
    assert set(artifact["importance"]) == {"rf", "xgboost"}
    for values in artifact["importance"].values():
        assert sum(values.values()) == pytest.approx(1.0)
        assert list(values.values()) == sorted(values.values(), reverse=True)


def test_training_refuses_too_little_history():
    with pytest.raises(ValueError, match="not enough history"):
        train(synthetic_series(5, "UTC"), "UTC", horizons=(15,), fast=True)


# ------------------------------------------------------------------------ model store


def test_store_without_a_model(tmp_path):
    assert ModelStore(tmp_path / "missing.joblib").get() is None


def test_store_reloads_when_the_file_changes(artifact, tmp_path):
    path = tmp_path / "model.joblib"
    save(artifact, path)
    store = ModelStore(path)
    assert store.get()["model"] == artifact["model"]

    joblib.dump({**artifact, "model": "linear"}, path)
    os.utime(path, (1, 1))  # a different mtime, whatever the file system's resolution
    assert store.get()["model"] == "linear"


def test_store_rejects_an_old_artifact(tmp_path):
    path = tmp_path / "model.joblib"
    joblib.dump({"version": 0}, path)
    assert ModelStore(path).get() is None


# ------------------------------------------------------------------------ API


@pytest.fixture
def ml_client(settings, store, history, account_repo, model_file):
    app = create_app(
        settings.model_copy(update={"model_path": str(model_file)}),
        store=store,
        history=history,
        account_repo=account_repo,
        background_tasks=False,
    )
    with TestClient(app) as c:
        yield c


def _fill_history(history, days: float = 8, until: datetime | None = None) -> None:
    end = (until or datetime.now(UTC)).replace(second=0, microsecond=0)
    snaps, _ = simulate(end - timedelta(days=days), end, ZoneInfo("UTC"), random.Random(3))
    history.snapshots.extend(snaps)


def test_endpoints_without_a_model(client):
    assert client.get("/api/v1/predictions").status_code == 503
    response = client.get("/api/v1/models/compare")
    assert response.status_code == 503
    assert "app.ml.train" in response.json()["detail"]


def test_predictions(ml_client, history):
    _fill_history(history)

    body = ml_client.get("/api/v1/predictions", params={"horizon": 60}).json()

    assert body["total_spots"] == 4
    assert body["stale"] is False
    assert [p["horizon_min"] for p in body["points"]] == [15, 60]
    for p in [body["current"], *body["points"]]:
        assert 0 <= p["rate"] <= 1
        assert p["free_spots"] == round(4 * (1 - p["rate"]))
    based_on = datetime.fromisoformat(body["based_on"])
    assert datetime.fromisoformat(body["points"][1]["ts"]) - based_on == timedelta(minutes=60)
    assert body["best"]["rate"] == min(p["rate"] for p in [body["current"], *body["points"]])


def test_horizon_limits_the_points(ml_client, history):
    _fill_history(history)
    body = ml_client.get("/api/v1/predictions", params={"horizon": 30}).json()
    assert [p["horizon_min"] for p in body["points"]] == [15]
    assert ml_client.get("/api/v1/predictions", params={"horizon": 10}).status_code == 422


def test_served_predictions_are_logged_once(ml_client, history):
    _fill_history(history)
    ml_client.get("/api/v1/predictions")
    ml_client.get("/api/v1/predictions")  # same data: answered from the cache

    assert len(history.predictions) == 2  # one per horizon
    logged = history.predictions[0]
    assert logged["horizon_min"] == 15
    assert logged["ts"] - logged["made_at"] == timedelta(minutes=15)


def test_predictions_need_a_week_of_history(ml_client, history):
    _fill_history(history, days=2)
    response = ml_client.get("/api/v1/predictions")
    assert response.status_code == 503
    assert "7 days" in response.json()["detail"]


def test_no_prediction_after_hours_without_data(ml_client, history):
    _fill_history(history, until=datetime.now(UTC) - timedelta(hours=12))
    response = ml_client.get("/api/v1/predictions")
    assert response.status_code == 503
    assert "sensors seem offline" in response.json()["detail"]


def test_old_data_is_flagged_stale(ml_client, history):
    _fill_history(history, until=datetime.now(UTC) - timedelta(hours=1))
    body = ml_client.get("/api/v1/predictions").json()
    assert body["stale"] is True


def test_models_compare(ml_client, artifact):
    body = ml_client.get("/api/v1/models/compare").json()

    assert body["best_model"] == artifact["model"]
    assert body["horizons"] == list(HORIZONS)
    assert len(body["results"]) == 4 * len(HORIZONS)
    assert {"mae", "rmse", "r2", "fit_s"} <= set(body["results"][0])
    top = body["feature_importance"]["rf"][0]
    assert top["label"] and 0 < top["importance"] <= 1
