"""Loads the model saved by the trainer, and reloads it when the file changes, so retraining
(`python -m app.ml.train`, or `docker compose run trainer`) needs no API restart."""

import logging
from pathlib import Path
from typing import Any

import joblib

from app.ml.train import ARTIFACT_VERSION

logger = logging.getLogger(__name__)


class ModelStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._artifact: dict[str, Any] | None = None
        self._mtime: float | None = None

    def get(self) -> dict[str, Any] | None:
        """The current artifact, or None if no (valid) model has been trained yet."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._artifact = self._mtime = None
            return None
        if mtime != self._mtime:
            self._mtime = mtime
            self._artifact = self._load()
        return self._artifact

    def _load(self) -> dict[str, Any] | None:
        try:
            artifact = joblib.load(self.path)
        except Exception:
            logger.exception("Could not load the model %s", self.path)
            return None
        if not isinstance(artifact, dict) or artifact.get("version") != ARTIFACT_VERSION:
            logger.error("%s is not a model of this version: retrain it", self.path)
            return None
        logger.info("Loaded the %s model trained at %s", artifact["model"], artifact["trained_at"])
        return artifact
