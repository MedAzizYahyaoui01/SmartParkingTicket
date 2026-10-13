"""ESP32 -> API -> MongoDB integration test, against a real MongoDB.

Runs when TEST_MONGO_URI is set (CI provides a MongoDB service container); skipped otherwise.
Firebase is replaced by the in-memory store so CI needs no cloud credentials.
"""

import os
import uuid

import pytest
from esp32_simulator import SimulatedParking
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.config import Settings
from app.main import create_app
from tests.conftest import API_KEY

MONGO_URI = os.environ.get("TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not MONGO_URI, reason="TEST_MONGO_URI not set")


@pytest.fixture
def mongo_db_name():
    name = f"test_smart_parking_{uuid.uuid4().hex[:8]}"
    yield name
    MongoClient(MONGO_URI).drop_database(name)


def test_simulated_esp32_flow_end_to_end(mongo_db_name, store):
    settings = Settings(
        _env_file=None, api_key=API_KEY, mongo_uri=MONGO_URI, mongo_db=mongo_db_name
    )
    app = create_app(settings, store=store, background_tasks=False)
    esp32 = SimulatedParking()
    headers = {"X-API-Key": API_KEY}
    url = "/api/v1/sensors/reading"

    with TestClient(app) as client:
        assert client.get("/health").json()["mongo"] == "up"

        # 1. Boot: everything free
        assert client.post(url, json=esp32.payload(), headers=headers).status_code == 200

        # 2. A car arrives at the gate -> the API answers "open"
        esp32.gate_distance = 20.0
        reply = client.post(url, json=esp32.payload(), headers=headers).json()
        assert reply["barrier_command"] == "open"
        esp32.apply_command(reply["barrier_command"])

        # 3. It parks on P2 -> one event in MongoDB, Firebase updated
        esp32.gate_distance = 300.0
        esp32.park("P2")
        client.post(url, json=esp32.payload(), headers=headers)

        # 4. A minute later, a snapshot is taken
        snapshot = client.portal.call(app.state.parking.take_snapshot)
        assert snapshot["rate"] == 0.25

    db = MongoClient(MONGO_URI)[mongo_db_name]
    events = list(db.occupancy_events.find({}, {"_id": 0}))
    assert [(e["spot_id"], e["occupied"]) for e in events] == [("P2", True)]
    assert db.occupancy_snapshots.count_documents({}) == 1
    assert "occupancy_snapshots" in db.list_collection_names(filter={"type": "timeseries"})
    assert store.get("parking/spots/P2/status") == "occupied"
    assert store.get("parking/summary")["free"] == 3
