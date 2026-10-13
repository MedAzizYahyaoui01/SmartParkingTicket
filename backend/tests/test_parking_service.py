"""Unit tests of the business rules (no network: in-memory stores and a fake clock)."""

from app.schemas.sensors import SensorReading
from tests.conftest import make_reading


def reading(**kwargs) -> SensorReading:
    return SensorReading.model_validate(make_reading(**kwargs))


# --- change detection -------------------------------------------------------


async def test_first_reading_sets_state_without_history_events(service, history, store):
    await service.handle_reading(reading(occupied=(True, False, False, False)))

    assert history.events == []  # first sighting is not a change
    assert store.get("parking/spots/P1/status") == "occupied"
    assert store.get("parking/spots/P2/status") == "free"
    assert store.get("parking/summary") == {"free": 3, "occupied": 1, "reserved": 0, "total": 4}


async def test_only_real_changes_are_recorded(service, history):
    await service.handle_reading(reading(occupied=(False, False, False, False)))
    await service.handle_reading(reading(occupied=(True, False, False, False)))  # P1 arrives
    await service.handle_reading(reading(occupied=(True, False, False, False)))  # heartbeat
    await service.handle_reading(reading(occupied=(False, False, False, False)))  # P1 leaves

    assert [(e["spot_id"], e["occupied"]) for e in history.events] == [
        ("P1", True),
        ("P1", False),
    ]


async def test_status_change_time_is_kept_on_heartbeat(service, store, clock):
    await service.handle_reading(reading(occupied=(True, False, False, False)))
    first = store.get("parking/spots/P1/updated_at")

    clock.advance(30)
    await service.handle_reading(reading(occupied=(True, False, False, False)))

    assert store.get("parking/spots/P1/updated_at") == first


async def test_restart_restores_state_from_firebase(store, history, settings, clock):
    from app.services.parking import ParkingService

    store.update({"parking/spots/P1": {"status": "occupied", "distance_cm": 20.0}})
    service = ParkingService(store, history, settings, clock=clock)
    await service.startup()

    # Same state as before the restart: not a change.
    await service.handle_reading(reading(occupied=(True, False, False, False)))
    assert history.events == []


# --- barrier ----------------------------------------------------------------


async def test_car_at_gate_with_free_spot_opens(service):
    response = await service.handle_reading(reading(gate=True))

    assert response.barrier_command == "open"
    assert response.free_spots == 4


async def test_car_at_gate_when_full_stays_closed(service):
    response = await service.handle_reading(reading(occupied=(True,) * 4, gate=True))

    assert response.barrier_command == "none"
    assert response.free_spots == 0


async def test_no_command_when_barrier_already_open(service):
    response = await service.handle_reading(reading(gate=True, barrier="open"))

    assert response.barrier_command == "none"


async def test_dashboard_command_wins_and_is_delivered_once(service, store):
    await service.submit_barrier_command("open")
    assert store.get("barrier/command/status") == "pending"

    first = await service.handle_reading(reading(occupied=(True,) * 4))  # full, no car
    second = await service.handle_reading(reading(occupied=(True,) * 4))

    assert first.barrier_command == "open"
    assert second.barrier_command == "none"
    assert store.get("barrier/command/status") == "delivered"


async def test_barrier_movement_is_logged_with_its_source(service, history):
    await service.submit_barrier_command("open")
    await service.handle_reading(reading())  # delivers the command
    await service.handle_reading(reading(barrier="opening"))  # device starts moving
    await service.handle_reading(reading(barrier="open"))
    await service.handle_reading(reading(barrier="closing"))  # closes on its own timer

    assert [(e["action"], e["source"]) for e in history.barrier_events] == [
        ("open", "dashboard"),
        ("close", "device"),
    ]


async def test_barrier_jump_without_intermediate_state_is_logged(service, history):
    await service.handle_reading(reading(gate=True))  # auto rule answers "open"
    await service.handle_reading(reading(barrier="open"))  # reported straight as "open"
    await service.handle_reading(reading(barrier="closed"))

    assert [(e["action"], e["source"]) for e in history.barrier_events] == [
        ("open", "auto"),
        ("close", "device"),
    ]


# --- device online / offline ------------------------------------------------


async def test_device_goes_offline_after_silence(service, store, clock):
    await service.handle_reading(reading())
    assert store.get("parking/device/online") is True

    clock.advance(10)
    assert await service.check_device_online() is False

    clock.advance(10)  # 20 s without a reading > 15 s
    assert await service.check_device_online() is True
    assert store.get("parking/device/online") is False
    assert service.get_state().device.online is False


# --- snapshots ----------------------------------------------------------------


async def test_snapshot_stores_the_occupancy_rate(service, history):
    await service.handle_reading(reading(occupied=(True, True, True, False)))

    snapshot = await service.take_snapshot()

    assert snapshot["occupied"] == 3
    assert snapshot["total"] == 4
    assert snapshot["rate"] == 0.75
    assert history.snapshots == [snapshot]


async def test_no_snapshot_while_device_offline(service, history):
    assert await service.take_snapshot() is None  # never seen
    assert history.snapshots == []


# --- resilience -----------------------------------------------------------------


async def test_reading_still_answers_when_mongo_is_down(service, history, store):
    history.available = False
    await service.handle_reading(reading())

    response = await service.handle_reading(reading(occupied=(True, False, False, False)))

    assert response.barrier_command == "none"
    assert store.get("parking/spots/P1/status") == "occupied"  # Firebase still updated
