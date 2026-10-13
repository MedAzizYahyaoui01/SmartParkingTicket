"""MongoDB connection, opened once at start-up and shared by the whole app."""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import get_settings

_client: AsyncMongoClient | None = None


def connect() -> None:
    global _client
    settings = get_settings()
    # The client connects lazily, so start-up never blocks if MongoDB is down.
    _client = AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_db() -> AsyncDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client is not initialised")
    return _client[get_settings().mongo_db]


async def ping() -> bool:
    """True if MongoDB answers within the timeout."""
    try:
        await get_db().command("ping")
        return True
    except Exception:
        return False
