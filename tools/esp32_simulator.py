"""ESP32 simulator: sends the same JSON as the firmware, so the backend can be tested
and demoed without opening Wokwi. Also reused by the integration tests and Locust.

Usage (from the repo root, with the API running):
    python tools/esp32_simulator.py --api-key <API_KEY>
    python tools/esp32_simulator.py --api-key <API_KEY> --speed 10   # 10x faster traffic
"""

import argparse
import random
import sys
import time
from dataclasses import dataclass, field

SPOT_IDS = ["P1", "P2", "P3", "P4"]
OCCUPIED_THRESHOLD_CM = 50.0


@dataclass
class SimulatedParking:
    """Physical state of the simulated parking: distance seen by each sensor."""

    device_id: str = "esp32-parking-01"
    distances: dict[str, float] = field(default_factory=lambda: dict.fromkeys(SPOT_IDS, 300.0))
    gate_distance: float = 300.0
    barrier_state: str = "closed"

    def park(self, spot_id: str) -> None:
        self.distances[spot_id] = round(random.uniform(8, 30), 1)

    def leave(self, spot_id: str) -> None:
        self.distances[spot_id] = round(random.uniform(150, 390), 1)

    def payload(self) -> dict:
        """The exact body of POST /api/v1/sensors/reading (docs/contracts/)."""
        return {
            "device_id": self.device_id,
            "spots": [
                {
                    "spot_id": sid,
                    "distance_cm": self.distances[sid],
                    "occupied": self.distances[sid] < OCCUPIED_THRESHOLD_CM,
                }
                for sid in SPOT_IDS
            ],
            "gate_car_detected": self.gate_distance < OCCUPIED_THRESHOLD_CM,
            "barrier_state": self.barrier_state,
        }

    def apply_command(self, command: str) -> None:
        """A real barrier takes time to move; here it moves instantly."""
        if command == "open":
            self.barrier_state = "open"
        elif command == "close":
            self.barrier_state = "closed"

    def random_step(self, rng: random.Random) -> str | None:
        """One random event (a car arrives, parks or leaves). Returns a description or None."""
        roll = rng.random()
        free = [s for s in SPOT_IDS if self.distances[s] >= OCCUPIED_THRESHOLD_CM]
        taken = [s for s in SPOT_IDS if s not in free]

        car_waiting = self.gate_distance < OCCUPIED_THRESHOLD_CM
        if car_waiting and self.barrier_state == "open" and free:
            # The car at the gate drives in once the barrier is open.
            spot = rng.choice(free)
            self.gate_distance = 300.0
            self.park(spot)
            self.barrier_state = "closed"  # closes behind the car
            return f"car drove in and parked on {spot}"
        if roll < 0.10 and not car_waiting:
            self.gate_distance = 20.0
            return "car arrived at the gate"
        # Parked cars keep leaving, even while a car waits (otherwise a full parking
        # with a car at the gate would never change again).
        if 0.10 <= roll < 0.20 and taken:
            spot = rng.choice(taken)
            self.leave(spot)
            return f"car left {spot}"
        return None


def main() -> None:
    import httpx  # imported here so tests can import this module without httpx installed

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--interval", type=float, default=5.0, help="heartbeat period (s)")
    parser.add_argument("--speed", type=float, default=1.0, help="traffic speed multiplier")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)  # show output live even when redirected
    rng = random.Random(args.seed)
    parking = SimulatedParking()
    endpoint = f"{args.url}/api/v1/sensors/reading"
    headers = {"X-API-Key": args.api_key}
    tick = 1.0 / args.speed
    last_sent = 0.0

    print(f"Sending to {endpoint} (Ctrl+C to stop)")
    with httpx.Client(timeout=5) as client:
        while True:
            event = parking.random_step(rng)
            now = time.monotonic()
            if event or now - last_sent >= args.interval:
                if event:
                    print(f"- {event}")
                try:
                    r = client.post(endpoint, json=parking.payload(), headers=headers)
                    r.raise_for_status()
                    body = r.json()
                    before = parking.barrier_state
                    parking.apply_command(body["barrier_command"])
                    if parking.barrier_state != before:
                        # like the firmware: a barrier change is reported right away
                        client.post(endpoint, json=parking.payload(), headers=headers)
                    occupied = sum(s["occupied"] for s in parking.payload()["spots"])
                    print(
                        f"  sent: {occupied}/4 occupied, barrier {parking.barrier_state}"
                        f" -> command {body['barrier_command']}, {body['free_spots']} free"
                    )
                except httpx.HTTPError as exc:
                    print(f"  ! {exc}")
                last_sent = now
            time.sleep(tick)


if __name__ == "__main__":
    main()
