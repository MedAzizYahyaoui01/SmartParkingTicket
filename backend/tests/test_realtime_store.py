from app.repositories.realtime import InMemoryRealtimeStore, build_realtime_store


def test_multi_path_update_and_get():
    store = InMemoryRealtimeStore()
    store.update({"parking/spots/P1": {"status": "free"}, "parking/summary/free": 4})

    assert store.get("parking/spots/P1/status") == "free"
    assert store.get("parking/summary") == {"free": 4}
    assert store.get("parking/missing") is None


def test_none_deletes_a_location():
    store = InMemoryRealtimeStore()
    store.update({"barrier/command": {"action": "open"}})
    store.update({"barrier/command": None})

    assert store.get("barrier/command") is None


def test_without_firebase_config_falls_back_to_memory():
    assert isinstance(build_realtime_store("", ""), InMemoryRealtimeStore)


def test_missing_credentials_file_falls_back_to_memory(tmp_path):
    store = build_realtime_store("https://example.firebaseio.com", str(tmp_path / "nope.json"))
    assert isinstance(store, InMemoryRealtimeStore)
