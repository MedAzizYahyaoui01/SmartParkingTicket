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
from tests.conftest import API_KEY, register

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


def test_stats_and_reservations_on_real_mongo(mongo_db_name, store):
    """The aggregation pipelines give the same results as the in-memory twin."""
    from datetime import UTC, datetime, timedelta

    settings = Settings(
        _env_file=None,
        api_key=API_KEY,
        mongo_uri=MONGO_URI,
        mongo_db=mongo_db_name,
        timezone="Africa/Tunis",
    )
    app = create_app(settings, store=store, background_tasks=False)
    monday_8h_utc = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)  # 09:00 in Tunis

    with TestClient(app) as client:
        # Seed one hour of snapshots (0.25 then 0.75) and one 30-minute stay on P1
        db = MongoClient(MONGO_URI)[mongo_db_name]
        db.occupancy_snapshots.insert_many(
            {
                "ts": monday_8h_utc + timedelta(minutes=m),
                "rate": 0.25 if m < 30 else 0.75,
                "occupied": 1 if m < 30 else 3,
                "total": 4,
            }
            for m in range(60)
        )
        db.occupancy_events.insert_many(
            [
                {"spot_id": "P1", "occupied": True, "ts": monday_8h_utc},
                {"spot_id": "P1", "occupied": False, "ts": monday_8h_utc + timedelta(minutes=30)},
            ]
        )
        period = {"from": "2026-10-12T00:00:00", "to": "2026-10-13T00:00:00"}

        series = client.get("/api/v1/stats/occupancy", params={**period, "step": 30}).json()
        assert [p["rate"] for p in series["points"]] == [0.25, 0.75]
        assert datetime.fromisoformat(series["points"][0]["ts"]) == monday_8h_utc

        summary = client.get("/api/v1/stats/summary", params=period).json()
        assert summary["samples"] == 60
        assert summary["avg_rate"] == 0.5
        assert summary["entries"] == 1
        assert summary["avg_duration_min"] == 30.0
        assert [(c["weekday"], c["hour"]) for c in summary["heatmap"]] == [(0, 9)]

        # Reservation lifecycle is logged in MongoDB
        client.post(
            "/api/v1/sensors/reading",
            json=SimulatedParking().payload(),
            headers={"X-API-Key": API_KEY},
        )
        user = register(client)
        uid = client.get("/api/v1/me", headers=user).json()["uid"]
        db.users.update_one({"_id": uid}, {"$inc": {"balance": 5000}})
        res_id = client.post("/api/v1/reservations", json={"spot_id": "P2"}, headers=user).json()[
            "id"
        ]
        assert client.delete(f"/api/v1/reservations/{res_id}", headers=user).status_code == 204

    assert db.reservations.find_one({"_id": res_id})["status"] == "cancelled"
    # The fee was paid, then refunded, and both moves are in the wallet statement
    assert db.users.find_one({"_id": uid})["balance"] == 5000
    kinds = [t["kind"] for t in db.wallet_transactions.find({"uid": uid}, sort=[("ts", 1)])]
    assert kinds == ["reservation_fee", "reservation_refund"]
