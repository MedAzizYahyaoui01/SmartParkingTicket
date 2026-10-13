# Smart Parking IoT — real-time availability and occupancy prediction

A connected 4-spot parking: an ESP32 (simulated in Wokwi) detects cars with ultrasonic sensors,
a FastAPI server stores the live state in Firebase and the history in MongoDB, an ML module
predicts the occupancy rate, and a React dashboard shows the live map, statistics, predictions
and simulated reservations.

The full design is in [`docs/project-report.pdf`](docs/project-report.pdf).

```
ESP32 (Wokwi) ──readings──▶ FastAPI ──current state──▶ Firebase RTDB ──live──▶ React dashboard
              ◀─barrier────         ──history────────▶ MongoDB                      │
                                    ◀──────────── REST (stats, predictions, reservations)
```

## Repository layout

| Folder | Content |
|---|---|
| `firmware/` | ESP32 firmware (PlatformIO + Wokwi circuit) |
| `backend/` | FastAPI API, business rules, ML module, PyTest suite |
| `frontend/` | React + Vite dashboard |
| `tools/` | ESP32 simulator and Locust load test |
| `docs/` | Report, architecture, API contracts |

## Development setup

| Where | What runs |
|---|---|
| Windows host | FastAPI (`localhost:8000`), React dev server, Wokwi in VS Code |
| VirtualBox VM "Docker VM" | Docker Compose: MongoDB, mongo-express (and later the full stack) |

The VM uses NAT networking, so its ports are forwarded to the host (bound to `127.0.0.1` only):

| Host port | VM port | Service |
|---|---|---|
| 27018 | 27018 | MongoDB of this project (27017 is left to another MongoDB on the VM) |
| 8081 | 8081 | mongo-express |
| 8001 | 8000 | API running in Docker |
| 8080 | 80 | Dashboard running in Docker |
| 2222 | 22 | SSH into the VM |

---

# Build log

Each step ends with something that runs. Steps are added as the project progresses.

## Step 1 — Project setup

**Goal:** a clean monorepo, MongoDB running in Docker, an empty FastAPI app with a health check,
and CI running on every push.

### What was done

- **Monorepo structure** following the report (`firmware/`, `backend/`, `frontend/`, `tools/`, `docs/`).
- **Secrets handling:** all secrets live in `.env` (git-ignored). `.env.example` documents every
  variable. Firebase service-account files are also git-ignored by pattern.
- **Backend skeleton** (`backend/app/`), layered as `routers/ → services/ → repositories/`
  with `schemas/` and `ml/`:
  - `config.py` — settings loaded from environment variables with `pydantic-settings`.
  - `db.py` — one async MongoDB client for the whole app. It uses PyMongo's native async API
    (`AsyncMongoClient`), the official successor of Motor, which reached end of life in 2026.
  - `routers/health.py` — `GET /health` returns `{"status": "ok", "version": ..., "mongo": "up"|"down"}`.
    It always answers 200 while the process is alive (a liveness check); the `mongo` field
    shows whether the database is reachable.
- **Docker Compose** with `mongo` (named volume, healthcheck, root user from `.env`),
  `mongo-express`, and the `api` service built from `backend/Dockerfile`.
- **Tests:** `tests/test_health.py` checks `/health` with MongoDB up and down (the ping is
  replaced by a fake, so the tests need no database).
- **CI** (`.github/workflows/ci.yml`): on every push/PR → ruff lint + format check →
  PyTest with coverage → Docker image build.

### Run it

**1. Start MongoDB in the VM**

```bash
git clone <repo-url> smart-parking && cd smart-parking
cp .env.example .env        # then set the same passwords as on Windows
docker compose up -d mongo mongo-express
docker compose ps           # mongo should be "healthy"
```

**2. Run the API on Windows**

```powershell
conda activate smart-parking
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000/health> → `{"status":"ok","version":"0.1.0","mongo":"up"}`
and <http://localhost:8000/docs> for the interactive API docs.
Browse the database at <http://localhost:8081>.

**3. Run the checks**

```powershell
ruff check . ; ruff format --check .
pytest --cov=app
```

## Step 2 — IoT layer: ESP32 firmware in Wokwi

**Goal:** a simulated ESP32 that detects cars on 4 spots and at the gate, shows each spot on
green/red LEDs, and opens a servo barrier — tested on its own with the serial monitor.

### Circuit (`firmware/diagram.json`)

| Spot | TRIG | ECHO | Green LED | Red LED |
|---|---|---|---|---|
| P1 | 4 | 34 | 16 (RX2) | 17 (TX2) |
| P2 | 5 | 35 | 18 | 19 |
| P3 | 23 | 36 (VP) | 25 | 26 |
| P4 | 27 | 39 (VN) | 32 | 33 |
| Gate | 13 | 14 | – | – |
| Servo | 21 (signal) | – | – | – |

ECHO pins use GPIO 34/35/36/39, which are input-only on the ESP32 — ideal for echo signals.
Every LED has a 220 Ω resistor. On real hardware the 5 V echo would need a voltage divider;
Wokwi doesn't need one.

### Firmware (`firmware/`)

| File | Role |
|---|---|
| `include/config.h` | Every pin, threshold and timing in one place |
| `include/Debouncer.h` | Stable state after N identical readings (pure C++, no Arduino dependency) |
| `include/Ultrasonic.h` | One HC-SR04 measurement in cm (timeout → 400 cm = nothing in range) |
| `include/Barrier.h`, `src/Barrier.cpp` | Servo barrier as a state machine |
| `src/main.cpp` | Scheduling, LEDs, gate rule, JSON report |

**How it works**

1. **Round-robin sensing.** Every 100 ms the firmware measures *one* sensor (P1 → P2 → P3 → P4
   → gate → P1 …), so each sensor is read every 500 ms and two sensors never fire at the same
   time (no echo crosstalk on real hardware).
2. **Occupied** when the distance is below 50 cm. **Debounce:** a spot only changes state after
   3 identical readings in a row (~1.5 s), so a slider passing by doesn't flicker. The gate uses 2.
3. **LEDs update immediately** on a change — local feedback that works even without network.
4. **Barrier state machine** (non-blocking, the servo moves 3° every 15 ms):

   ```
   CLOSED ──car at gate & free spot──▶ OPENING ──90°──▶ OPEN
   OPEN ──gate clear for 5 s──▶ CLOSING ──0°──▶ CLOSED
   CLOSING ──car appears──▶ OPENING      (safety: never close on a car)
   ```
   If the parking is full, the barrier stays closed and the serial monitor says so.
5. **Report** in the API's JSON format (`docs/contracts/sensor-reading.schema.json`):
   immediately on any change, plus a heartbeat every 5 s. In this step it is printed on the
   serial monitor; in Step 4 the same JSON is sent to the API over Wi-Fi.

Everything is scheduled with `millis()` — there is no `delay()` in the code. The only waits are
the 10 µs trigger pulse and `pulseIn()`, bounded at 25 ms.

### Run it

1. Open the `firmware/` folder in VS Code (PlatformIO and Wokwi extensions installed).
2. Build: PlatformIO sidebar → *Build*, or `pio run` in a terminal.
3. `F1` → **Wokwi: Start Simulator** (first time: activate your Wokwi license).
4. Click a sensor and move its distance slider below 50 cm:

```
[spot] P1 -> occupied (23.0 cm), 3/4 free
[report:change] {"device_id":"esp32-parking-01","spots":[{"spot_id":"P1","distance_cm":23,"occupied":true}, ...],"gate_car_detected":false,"barrier_state":"closed"}
```

5. Move the **GATE** sensor below 50 cm → the servo opens to 90°; move it back above 50 cm →
   it closes 5 s later. With all 4 spots occupied, the barrier stays closed.
