import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.accounts import InMemoryAccountRepository
from app.repositories.history import InMemoryHistoryRepository
from app.repositories.realtime import InMemoryRealtimeStore
from app.services.parking import ParkingService

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))  # makes esp32_simulator importable

API_KEY = "test-key"
SPOT_IDS = ["P1", "P2", "P3", "P4"]


class FakeClock:
    """Controllable time, so time-based rules are tested without sleeping."""

    def __init__(self, start: float = 1_760_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_reading(
    occupied: tuple[bool, bool, bool, bool] = (False, False, False, False),
    gate: bool = False,
    barrier: str = "closed",
) -> dict:
    """A sensor reading in the firmware's JSON format."""
    return {
        "device_id": "esp32-parking-01",
        "spots": [
            {"spot_id": sid, "distance_cm": 20.0 if occ else 300.0, "occupied": occ}
            for sid, occ in zip(SPOT_IDS, occupied, strict=True)
        ],
        "gate_car_detected": gate,
        "barrier_state": barrier,
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, api_key=API_KEY, firebase_database_url="")


@pytest.fixture
def store() -> InMemoryRealtimeStore:
    return InMemoryRealtimeStore()


@pytest.fixture
def history() -> InMemoryHistoryRepository:
    return InMemoryHistoryRepository()


@pytest.fixture
def account_repo() -> InMemoryAccountRepository:
    return InMemoryAccountRepository()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(store, history, settings, clock) -> ParkingService:
    return ParkingService(store, history, settings, clock=clock)


@pytest.fixture
def client(settings, store, history, account_repo):
    app = create_app(
        settings, store=store, history=history, account_repo=account_repo, background_tasks=False
    )
    with TestClient(app) as c:
        yield c


def register(client, email: str = "amine@example.com", name: str = "Amine") -> dict:
    """Creates an account through the API; returns its Authorization header."""
    response = client.post(
        "/api/v1/auth/register", json={"name": name, "email": email, "password": "secret-pass"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def credit(account_repo, user_headers: dict, client, amount: int) -> None:
    """Puts money in the wallet directly (top-ups are tested in test_payments)."""
    uid = client.get("/api/v1/me", headers=user_headers).json()["uid"]
    account_repo.users[uid]["balance"] += amount


@pytest.fixture
def auth() -> dict:
    return {"X-API-Key": API_KEY}
