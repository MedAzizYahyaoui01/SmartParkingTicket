"""Gate access in "account" mode: who may enter, and what leaving costs."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import API_KEY, credit, make_reading, register

READING = "/api/v1/sensors/reading"
SENSORS = {"X-API-Key": API_KEY}


@pytest.fixture
def account_settings() -> Settings:
    return Settings(_env_file=None, api_key=API_KEY, gate_mode="account")


@pytest.fixture
def api(account_settings, store, history, account_repo, clock):
    app = create_app(
        account_settings,
        store=store,
        history=history,
        account_repo=account_repo,
        background_tasks=False,
    )
    with TestClient(app) as c:
        # The fake clock drives both the parking (reservations) and the accounts (stays)
        c.app.state.parking.clock = clock
        c.app.state.accounts.clock = clock
        c.post(READING, json=make_reading(occupied=(True, False, False, False)), headers=SENSORS)
        yield c


@pytest.fixture
def user(api, account_repo):
    headers = register(api)
    credit(account_repo, headers, api, 5000)
    return headers


def test_in_account_mode_a_car_at_the_gate_does_not_open_it(api):
    reply = api.post(READING, json=make_reading(gate=True), headers=SENSORS).json()
    assert reply == {"barrier_command": "none", "free_spots": 4, "gate_mode": "account"}


def test_identified_user_with_credit_enters(api, user):
    decision = api.post("/api/v1/gate/enter", headers=user).json()
    assert (decision["allowed"], decision["reason"]) == (True, "ok")

    # The ESP32 gets the command in its next heartbeat
    reply = api.post(READING, json=make_reading(gate=True), headers=SENSORS).json()
    assert reply["barrier_command"] == "open"
    me = api.get("/api/v1/me", headers=user).json()
    assert me["stay"] is not None


def test_entering_twice_is_refused(api, user):
    api.post("/api/v1/gate/enter", headers=user)
    assert api.post("/api/v1/gate/enter", headers=user).json()["reason"] == "already_inside"


def test_low_balance_is_refused(api):
    poor = register(api, "poor@example.com", "Poor")
    decision = api.post("/api/v1/gate/enter", headers=poor).json()
    assert (decision["allowed"], decision["reason"]) == (False, "low_balance")


def test_full_parking_is_refused_unless_you_have_a_reservation(api, user, account_repo):
    other = register(api, "sara@example.com", "Sara")
    credit(account_repo, other, api, 5000)
    # 3 spots occupied, the last free one reserved by Sara
    api.post(READING, json=make_reading(occupied=(True, True, True, False)), headers=SENSORS)
    assert (
        api.post("/api/v1/reservations", json={"spot_id": "P4"}, headers=other).status_code == 201
    )

    assert api.post("/api/v1/gate/enter", headers=user).json()["reason"] == "full"
    sara = api.post("/api/v1/gate/enter", headers=other).json()
    assert (sara["allowed"], sara["spot_hint"]) == (True, "P4")


def test_exit_charges_the_stay(api, user, clock):
    api.post("/api/v1/gate/enter", headers=user)
    clock.advance(40 * 60)  # 40 min: 15 free + 2 started blocks of 15 min

    decision = api.post("/api/v1/gate/exit", headers=user).json()
    assert (decision["allowed"], decision["minutes"], decision["fee"]) == (True, 40, 1000)
    assert decision["balance"] == 4000
    me = api.get("/api/v1/me", headers=user).json()
    assert me["stay"] is None
    tx = api.get("/api/v1/me/transactions", headers=user).json()
    assert tx[0]["kind"] == "parking" and tx[0]["amount"] == -1000


def test_a_long_stay_can_end_in_debt_which_blocks_entry_and_reservations(api, user, clock):
    api.post("/api/v1/gate/enter", headers=user)
    clock.advance(4 * 3600)  # 4 h = 7.5 TND with a 5 TND balance

    decision = api.post("/api/v1/gate/exit", headers=user).json()
    assert decision["allowed"]  # never trapped inside
    assert decision["balance"] < 0
    assert api.get("/api/v1/me", headers=user).json()["status"] == "debt"
    assert api.post("/api/v1/gate/enter", headers=user).json()["reason"] == "debt"
    assert api.post("/api/v1/reservations", json={"spot_id": "P2"}, headers=user).status_code == 403


def test_leaving_releases_an_unused_reservation(api, user):
    api.post("/api/v1/reservations", json={"spot_id": "P2"}, headers=user)
    api.post("/api/v1/gate/enter", headers=user)
    api.post("/api/v1/gate/exit", headers=user)

    assert api.get("/api/v1/reservations").json() == []
    assert api.get("/api/v1/spots").json()["spots"][1]["status"] == "free"


def test_exit_without_a_stay_is_refused(api, user):
    assert api.post("/api/v1/gate/exit", headers=user).json()["reason"] == "not_inside"


def test_kiosk_session_can_open_the_gate(api, user):
    code = api.post("/api/v1/me/access-code", headers=user).json()["code"]
    token = api.post("/api/v1/gate/identify", json={"code": code}).json()["token"]

    decision = api.post("/api/v1/gate/enter", headers={"Authorization": f"Bearer {token}"})
    assert decision.json()["allowed"]
