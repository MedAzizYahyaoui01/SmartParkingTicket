"""Live state store: Firebase Realtime Database, or an in-memory stand-in.

Paths are slash-separated ("parking/spots/P1"). `update` is a multi-path update at the
root: every key is a full path, so many locations change in one request; a None value
deletes that location (same semantics as Firebase).
"""

import copy
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RealtimeStore(Protocol):
    def get(self, path: str) -> Any: ...
    def update(self, values: dict[str, Any]) -> None: ...


class InMemoryRealtimeStore:
    """Same behaviour as Firebase, kept in a dict. Used by tests and when Firebase is off."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, path: str) -> Any:
        node: Any = self.data
        for key in _split(path):
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return copy.deepcopy(node)

    def update(self, values: dict[str, Any]) -> None:
        for path, value in values.items():
            *parents, leaf = _split(path)
            node = self.data
            for key in parents:
                node = node.setdefault(key, {})
            if value is None:
                node.pop(leaf, None)
            else:
                node[leaf] = copy.deepcopy(value)


class FirebaseRealtimeStore:
    """Writes through the Admin SDK with a service account (bypasses security rules)."""

    def __init__(self, credentials_path: str, database_url: str) -> None:
        import firebase_admin
        from firebase_admin import credentials, db

        cred = credentials.Certificate(credentials_path)
        try:
            app = firebase_admin.get_app("smart-parking")
        except ValueError:
            app = firebase_admin.initialize_app(
                cred, {"databaseURL": database_url}, name="smart-parking"
            )
        self._root = db.reference("/", app=app)

    def get(self, path: str) -> Any:
        return self._root.child(path).get()

    def update(self, values: dict[str, Any]) -> None:
        self._root.update(values)


def build_realtime_store(database_url: str, credentials_path: str) -> RealtimeStore:
    if database_url and credentials_path:
        if Path(credentials_path).is_file():
            logger.info("Live state: Firebase Realtime Database (%s)", database_url)
            return FirebaseRealtimeStore(credentials_path, database_url)
        logger.error("Firebase credentials file not found: %s", credentials_path)
    logger.warning("Firebase not configured: live state is kept in memory only")
    return InMemoryRealtimeStore()


def _split(path: str) -> list[str]:
    return [p for p in path.split("/") if p]
