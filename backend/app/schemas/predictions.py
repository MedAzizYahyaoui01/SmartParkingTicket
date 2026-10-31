"""Occupancy predictions and the model comparison."""

from datetime import datetime

from pydantic import BaseModel


class PredictionPoint(BaseModel):
    horizon_min: int  # 0 = now
    ts: datetime
    rate: float  # 0..1
    free_spots: int  # total x (1 - rate), rounded


class PredictionsOut(BaseModel):
    model: str
    label: str
    trained_at: datetime
    based_on: datetime  # the latest 5-min bucket of history the prediction starts from
    stale: bool  # no recent data (sensors offline): the prediction starts from older data
    total_spots: int
    current: PredictionPoint
    points: list[PredictionPoint]
    best: PredictionPoint  # least busy moment among now and the predicted points


class ModelResult(BaseModel):
    model: str
    label: str
    horizon_min: int
    mae: float
    rmse: float
    r2: float
    fit_s: float
    predict_s: float
    train_rows: int
    test_rows: int


class FeatureImportance(BaseModel):
    feature: str
    label: str
    importance: float  # share of the total, 0..1


class DataPeriod(BaseModel):
    start: datetime
    end: datetime
    points: int  # points of history on the model's grid (all series together)
    train_until: datetime  # time-based split: train before, test after


class TrainingData(DataPeriod):
    source: str


class BenchmarkOut(BaseModel):
    """The same comparison on another dataset (scores only, not used for predictions)."""

    name: str
    title: str
    source: str
    url: str
    best_model: str
    label: str
    step_min: int
    horizons: list[int]
    data: DataPeriod
    mean_mae: dict[str, float]
    results: list[ModelResult]
    feature_importance: dict[str, list[FeatureImportance]]


class ModelsCompareOut(BaseModel):
    best_model: str
    label: str
    trained_at: datetime
    timezone: str
    horizons: list[int]
    data: TrainingData
    mean_mae: dict[str, float]
    results: list[ModelResult]
    feature_importance: dict[str, list[FeatureImportance]]  # rf and xgboost only
    benchmarks: list[BenchmarkOut]  # e.g. the real Birmingham car parks, if trained with it
