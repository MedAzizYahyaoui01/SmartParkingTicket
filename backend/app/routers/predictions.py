from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_predictions
from app.schemas.predictions import ModelsCompareOut, PredictionsOut
from app.services.predictions import (
    ModelNotReadyError,
    NotEnoughHistoryError,
    PredictionService,
)

router = APIRouter(tags=["predictions"])

Predictions = Annotated[PredictionService, Depends(get_predictions)]


@router.get("/predictions", response_model=PredictionsOut)
async def predictions(
    service: Predictions,
    horizon: Annotated[int, Query(ge=1, description="Predict up to this many minutes")] = 60,
) -> PredictionsOut:
    """Predicted occupancy rate (and free spots) at each trained horizon up to `horizon`,
    plus the least busy moment among them."""
    try:
        return await service.predict(horizon)
    except (ModelNotReadyError, NotEnoughHistoryError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.get("/models/compare", response_model=ModelsCompareOut)
async def compare_models(service: Predictions) -> ModelsCompareOut:
    """MAE / RMSE / R² of every model on the test period, per horizon, and the feature
    importance of the tree models."""
    try:
        return service.compare()
    except ModelNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
