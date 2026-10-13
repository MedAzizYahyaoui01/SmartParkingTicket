"""MongoDB connection, opened once at start-up and shared by the whole app."""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

_client: AsyncMongoClient | None = None


def connect(uri: str) -> None:
    global _client
    # The client connects lazily, so start-up never blocks if MongoDB is down.
    _client = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000, tz_aware=True)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_db(name: str) -> AsyncDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client is not initialised")
    return _client[name]
