"""ESP32 <-> API contract: the JSON schema in docs/contracts/ is the single source of truth.
The simulator, the schema's own example and the API must all agree with it."""

import json
import random

import jsonschema
import pytest
from esp32_simulator import SimulatedParking

from tests.conftest import REPO_ROOT

SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "contracts" / "sensor-reading.schema.json").read_text(encoding="utf-8")
)


def test_schema_example_is_valid():
    for example in SCHEMA["examples"]:
        jsonschema.validate(example, SCHEMA)


@pytest.mark.parametrize("seed", range(5))
def test_simulator_payloads_match_the_schema(seed):
    rng = random.Random(seed)
    parking = SimulatedParking()
    for _ in range(50):
        parking.random_step(rng)
        jsonschema.validate(parking.payload(), SCHEMA)


def test_api_accepts_the_schema_example(client, auth):
    response = client.post("/api/v1/sensors/reading", json=SCHEMA["examples"][0], headers=auth)
    assert response.status_code == 200
