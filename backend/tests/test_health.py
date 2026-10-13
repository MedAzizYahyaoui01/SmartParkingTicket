from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_health_returns_ok_with_mongo_up(monkeypatch):
    async def fake_ping() -> bool:
        return True

    monkeypatch.setattr(db, "ping", fake_ping)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mongo"] == "up"
    assert "version" in body


def test_health_still_ok_when_mongo_is_down(monkeypatch):
    async def fake_ping() -> bool:
        return False

    monkeypatch.setattr(db, "ping", fake_ping)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["mongo"] == "down"
