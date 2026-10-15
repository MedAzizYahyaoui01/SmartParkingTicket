"""Reservations: business rules (service) and HTTP behaviour (API)."""

import pytest

from app.schemas.sensors import SensorReading
from app.services.parking import ReservationNotFoundError, SpotUnavailableError
from tests.conftest import make_reading

URL = "/api/v1/reservations"
READING_URL = "/api/v1/sensors/reading"


def reading(**kwargs) -> SensorReading:
    return SensorReading.model_validate(make_reading(**kwargs))


@pytest.fixture
async def ready(service):
    """Service after a first reading: P1 occupied, P2-P4 free."""
    await service.handle_reading(reading(occupied=(True, False, False, False)))
    return service


# --- service ------------------------------------------------------------------


async def test_reserving_a_free_spot_marks_it_reserved(ready, store, history):
    res = await ready.create_reservation("P2", "Amine", 15)

    assert res.status == "active"
    assert res.expires_at - res.created_at == 15 * 60
    assert store.get("parking/spots/P2/status") == "reserved"
    assert store.get(f"reservations/{res.id}")["name"] == "Amine"
    assert store.get("parking/summary") == {"free": 2, "occupied": 1, "reserved": 1, "total": 4}
    assert history.reservations[res.id]["status"] == "active"


async def test_reserved_spot_cannot_be_reserved_twice(ready):
    await ready.create_reservation("P2", "Amine")
    with pytest.raises(SpotUnavailableError, match="already reserved"):
        await ready.create_reservation("P2", "Sara")


async def test_occupied_spot_cannot_be_reserved(ready):
    with pytest.raises(SpotUnavailableError, match="occupied"):
        await ready.create_reservation("P1", "Amine")


async def test_spot_with_unknown_state_cannot_be_reserved(service):
    with pytest.raises(SpotUnavailableError, match="unknown"):
        await service.create_reservation("P1", "Amine")


async def test_duration_above_the_maximum_is_refused(ready, settings):
    with pytest.raises(ValueError):
        await ready.create_reservation("P2", "Amine", settings.reservation_max_min + 1)


async def test_reservation_expires_after_its_duration(ready, store, history, clock):
    res = await ready.create_reservation("P2", "Amine", 15)

    clock.advance(15 * 60 - 1)
    assert await ready.expire_reservations() == []

    clock.advance(1)
    assert await ready.expire_reservations() == [res.id]
    assert store.get("parking/spots/P2/status") == "free"
    assert store.get(f"reservations/{res.id}") is None
    assert history.reservations[res.id]["status"] == "expired"


async def test_cancel_releases_the_spot(ready, store, history):
    res = await ready.create_reservation("P2", "Amine")
    await ready.cancel_reservation(res.id)

    assert store.get("parking/spots/P2/status") == "free"
    assert history.reservations[res.id]["status"] == "cancelled"
    with pytest.raises(ReservationNotFoundError):
        await ready.cancel_reservation(res.id)


async def test_car_parking_on_reserved_spot_fulfils_the_reservation(ready, store, history):
    res = await ready.create_reservation("P2", "Amine")
    await ready.handle_reading(reading(occupied=(True, True, False, False)))

    assert ready.list_reservations() == []
    assert store.get("parking/spots/P2/status") == "occupied"
    assert store.get(f"reservations/{res.id}") is None
    assert history.reservations[res.id]["status"] == "fulfilled"


async def test_heartbeat_keeps_the_spot_reserved(ready, store):
    await ready.create_reservation("P2", "Amine")
    await ready.handle_reading(reading(occupied=(True, False, False, False)))

    assert store.get("parking/spots/P2/status") == "reserved"


async def test_reserved_spot_does_not_count_as_free_for_the_barrier(service):
    await service.handle_reading(reading(occupied=(True, True, True, False)))
    await service.create_reservation("P4", "Amine")

    reply = await service.handle_reading(reading(occupied=(True, True, True, False), gate=True))
    assert reply.barrier_command == "none"
    assert reply.free_spots == 0


async def test_reservations_survive_an_api_restart(ready, store, history, settings, clock):
    from app.services.parking import ParkingService

    res = await ready.create_reservation("P2", "Amine")
    restarted = ParkingService(store, history, settings, clock=clock)
    await restarted.startup()

    assert [r.id for r in restarted.list_reservations()] == [res.id]
    assert restarted.get_state().spots[1].status == "reserved"


# --- API ----------------------------------------------------------------------


@pytest.fixture
def api(client, auth):
    """API client after a first reading: P1 occupied, P2-P4 free."""
    client.post(READING_URL, json=make_reading(occupied=(True, False, False, False)), headers=auth)
    return client


def test_post_reservation_returns_201(api):
    response = api.post(URL, json={"name": "Amine", "spot_id": "P2"})

    assert response.status_code == 201
    assert response.json()["spot_id"] == "P2"
    assert api.get(URL).json()[0]["id"] == response.json()["id"]
    assert api.get("/api/v1/spots").json()["spots"][1]["status"] == "reserved"


def test_reserving_twice_returns_409(api):
    api.post(URL, json={"name": "Amine", "spot_id": "P2"})
    assert api.post(URL, json={"name": "Sara", "spot_id": "P2"}).status_code == 409


def test_reserving_an_occupied_spot_returns_409(api):
    assert api.post(URL, json={"name": "Amine", "spot_id": "P1"}).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Amine", "spot_id": "P9"},
        {"name": "", "spot_id": "P2"},
        {"name": "Amine", "spot_id": "P2", "duration_min": 0},
        {"name": "Amine", "spot_id": "P2", "duration_min": 61},
        {"name": "Amine", "spot_id": "P2", "extra": 1},
    ],
)
def test_invalid_reservation_returns_422(api, body):
    assert api.post(URL, json=body).status_code == 422


def test_delete_reservation(api):
    res_id = api.post(URL, json={"name": "Amine", "spot_id": "P2"}).json()["id"]

    assert api.delete(f"{URL}/{res_id}").status_code == 204
    assert api.delete(f"{URL}/{res_id}").status_code == 404
    assert api.get(URL).json() == []
