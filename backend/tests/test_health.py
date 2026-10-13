def test_health_returns_ok_with_mongo_up(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mongo"] == "up"
    assert "version" in body


def test_health_still_ok_when_mongo_is_down(client, history):
    history.available = False

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["mongo"] == "down"
