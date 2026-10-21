"""API tests: status codes, validation and security of every endpoint."""

from tests.conftest import make_reading

READING_URL = "/api/v1/sensors/reading"


# --- POST /sensors/reading ----------------------------------------------------


def test_valid_reading_returns_barrier_command(client, auth):
    response = client.post(READING_URL, json=make_reading(gate=True), headers=auth)

    assert response.status_code == 200
    assert response.json() == {
        "barrier_command": "open",
        "free_spots": 4,
        "gate_mode": "auto",
    }


def test_reading_without_api_key_is_rejected(client):
    response = client.post(READING_URL, json=make_reading())
    assert response.status_code == 401


def test_reading_with_wrong_api_key_is_rejected(client):
    response = client.post(READING_URL, json=make_reading(), headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_unknown_spot_is_rejected(client, auth):
    body = make_reading()
    body["spots"][0]["spot_id"] = "P9"
    assert client.post(READING_URL, json=body, headers=auth).status_code == 422


def test_negative_distance_is_rejected(client, auth):
    body = make_reading()
    body["spots"][0]["distance_cm"] = -5
    assert client.post(READING_URL, json=body, headers=auth).status_code == 422


def test_duplicate_spot_is_rejected(client, auth):
    body = make_reading()
    body["spots"][1]["spot_id"] = "P1"
    assert client.post(READING_URL, json=body, headers=auth).status_code == 422


def test_unknown_field_is_rejected(client, auth):
    body = make_reading()
    body["temperature"] = 21
    assert client.post(READING_URL, json=body, headers=auth).status_code == 422


def test_malformed_json_is_rejected(client, auth):
    response = client.post(
        READING_URL,
        content=b'{"device_id": "esp32", "spots": [',
        headers={**auth, "Content-Type": "application/json"},
    )
    assert response.status_code == 422


# --- GET /spots -----------------------------------------------------------------


def test_spots_before_any_reading_are_unknown(client):
    body = client.get("/api/v1/spots").json()

    assert [s["status"] for s in body["spots"]] == ["unknown"] * 4
    assert body["device"]["online"] is False


def test_spots_reflect_the_last_reading(client, auth):
    client.post(READING_URL, json=make_reading(occupied=(True, False, True, False)), headers=auth)

    body = client.get("/api/v1/spots").json()

    assert [s["status"] for s in body["spots"]] == ["occupied", "free", "occupied", "free"]
    assert body["summary"] == {"free": 2, "occupied": 2, "reserved": 0, "total": 4}
    assert body["device"]["online"] is True


# --- POST /barrier/command ------------------------------------------------------


def test_barrier_command_reaches_the_esp32(client, auth):
    response = client.post("/api/v1/barrier/command", json={"action": "open"})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    reply = client.post(READING_URL, json=make_reading(), headers=auth).json()
    assert reply["barrier_command"] == "open"


def test_invalid_barrier_action_is_rejected(client):
    response = client.post("/api/v1/barrier/command", json={"action": "explode"})
    assert response.status_code == 422
