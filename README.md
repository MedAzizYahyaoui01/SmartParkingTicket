# Smart Parking IoT â€” real-time availability and occupancy prediction

A connected 4-spot parking: an ESP32 (simulated in Wokwi) detects cars with ultrasonic sensors,
a FastAPI server stores the live state in Firebase and the history in MongoDB, an ML module
predicts the occupancy rate, and a React dashboard shows the live map, statistics, predictions
and simulated reservations.

The full design is in [`docs/project-report.pdf`](docs/project-report.pdf).

```
ESP32 (Wokwi) â”€â”€readingsâ”€â”€â–¶ FastAPI â”€â”€current stateâ”€â”€â–¶ Firebase RTDB â”€â”€liveâ”€â”€â–¶ React dashboard
              â—€â”€barrierâ”€â”€â”€â”€         â”€â”€historyâ”€â”€â”€â”€â”€â”€â”€â”€â–¶ MongoDB                      â”‚
                                    â—€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ REST (stats, predictions, reservations)
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

## Step 1 â€” Project setup

**Goal:** a clean monorepo, MongoDB running in Docker, an empty FastAPI app with a health check,
and CI running on every push.

### What was done

- **Monorepo structure** following the report (`firmware/`, `backend/`, `frontend/`, `tools/`, `docs/`).
- **Secrets handling:** all secrets live in `.env` (git-ignored). `.env.example` documents every
  variable. Firebase service-account files are also git-ignored by pattern.
- **Backend skeleton** (`backend/app/`), layered as `routers/ â†’ services/ â†’ repositories/`
  with `schemas/` and `ml/`:
  - `config.py` â€” settings loaded from environment variables with `pydantic-settings`.
  - `db.py` â€” one async MongoDB client for the whole app. It uses PyMongo's native async API
    (`AsyncMongoClient`), the official successor of Motor, which reached end of life in 2026.
  - `routers/health.py` â€” `GET /health` returns `{"status": "ok", "version": ..., "mongo": "up"|"down"}`.
    It always answers 200 while the process is alive (a liveness check); the `mongo` field
    shows whether the database is reachable.
- **Docker Compose** with `mongo` (named volume, healthcheck, root user from `.env`),
  `mongo-express`, and the `api` service built from `backend/Dockerfile`.
- **Tests:** `tests/test_health.py` checks `/health` with MongoDB up and down (the ping is
  replaced by a fake, so the tests need no database).
- **CI** (`.github/workflows/ci.yml`): on every push/PR â†’ ruff lint + format check â†’
  PyTest with coverage â†’ Docker image build.

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

Open <http://localhost:8000/health> â†’ `{"status":"ok","version":"0.1.0","mongo":"up"}`
and <http://localhost:8000/docs> for the interactive API docs.
Browse the database at <http://localhost:8081>.

**3. Run the checks**

```powershell
ruff check . ; ruff format --check .
pytest --cov=app
```

## Step 2 â€” IoT layer: ESP32 firmware in Wokwi

**Goal:** a simulated ESP32 that detects cars on 4 spots and at the gate, shows each spot on
green/red LEDs, and opens a servo barrier â€” tested on its own with the serial monitor.

### Circuit (`firmware/diagram.json`)

| Spot | TRIG | ECHO | Green LED | Red LED |
|---|---|---|---|---|
| P1 | 4 | 34 | 16 (RX2) | 17 (TX2) |
| P2 | 5 | 35 | 18 | 19 |
| P3 | 23 | 36 (VP) | 25 | 26 |
| P4 | 27 | 39 (VN) | 32 | 33 |
| Gate | 13 | 14 | â€“ | â€“ |
| Servo | 21 (signal) | â€“ | â€“ | â€“ |

ECHO pins use GPIO 34/35/36/39, which are input-only on the ESP32 â€” ideal for echo signals.
Every LED has a 220 Î© resistor. On real hardware the 5 V echo would need a voltage divider;
Wokwi doesn't need one.

### Firmware (`firmware/`)

| File | Role |
|---|---|
| `include/config.h` | Every pin, threshold and timing in one place |
| `include/Debouncer.h` | Stable state after N identical readings (pure C++, no Arduino dependency) |
| `include/Ultrasonic.h` | One HC-SR04 measurement in cm (timeout â†’ 400 cm = nothing in range) |
| `include/Barrier.h`, `src/Barrier.cpp` | Servo barrier as a state machine |
| `src/main.cpp` | Scheduling, LEDs, gate rule, JSON report |

**How it works**

1. **Round-robin sensing.** Every 100 ms the firmware measures *one* sensor (P1 â†’ P2 â†’ P3 â†’ P4
   â†’ gate â†’ P1 â€¦), so each sensor is read every 500 ms and two sensors never fire at the same
   time (no echo crosstalk on real hardware).
2. **Occupied** when the distance is below 50 cm. **Debounce:** a spot only changes state after
   3 identical readings in a row (~1.5 s), so a slider passing by doesn't flicker. The gate uses 2.
3. **LEDs update immediately** on a change â€” local feedback that works even without network.
4. **Barrier state machine** (non-blocking, the servo moves 3Â° every 15 ms):

   ```
   CLOSED â”€â”€car at gate & free spotâ”€â”€â–¶ OPENING â”€â”€90Â°â”€â”€â–¶ OPEN
   OPEN â”€â”€gate clear for 5 sâ”€â”€â–¶ CLOSING â”€â”€0Â°â”€â”€â–¶ CLOSED
   CLOSING â”€â”€car appearsâ”€â”€â–¶ OPENING      (safety: never close on a car)
   ```
   If the parking is full, the barrier stays closed and the serial monitor says so.
5. **Report** in the API's JSON format (`docs/contracts/sensor-reading.schema.json`):
   immediately on any change, plus a heartbeat every 5 s (2 s from Step 4). In this step it is printed on the
   serial monitor; in Step 4 the same JSON is sent to the API over Wi-Fi.

Everything is scheduled with `millis()` â€” there is no `delay()` in the code. The only waits are
the 10 Âµs trigger pulse and `pulseIn()`, bounded at 25 ms.

### Run it

1. Open the `firmware/` folder in VS Code (PlatformIO and Wokwi extensions installed).
2. Build: PlatformIO sidebar â†’ *Build*, or `pio run` in a terminal.
3. `F1` â†’ **Wokwi: Start Simulator** (first time: activate your Wokwi license).
4. Click a sensor and move its distance slider below 50 cm:

```
[spot] P1 -> occupied (23.0 cm), 3/4 free
[report:change] {"device_id":"esp32-parking-01","spots":[{"spot_id":"P1","distance_cm":23,"occupied":true}, ...],"gate_car_detected":false,"barrier_state":"closed"}
```

5. Move the **GATE** sensor below 50 cm â†’ the servo opens to 90Â°; move it back above 50 cm â†’
   it closes 5 s later. With all 4 spots occupied, the barrier stays closed.

## Step 3 â€” API + databases

**Goal:** the API receives the ESP32 readings, keeps the *current* state in Firebase, the
*history* in MongoDB, and answers with the barrier command.

### Endpoints added

| Method | Route | Used by | Purpose |
|---|---|---|---|
| POST | `/api/v1/sensors/reading` | ESP32 (needs `X-API-Key`) | Receive spot states, return the barrier command |
| GET | `/api/v1/spots` | Dashboard | Current state of every spot, device and barrier |
| POST | `/api/v1/barrier/command` | Dashboard | Manual `open` / `close`, delivered in the ESP32's next response |

Request/response example:

```
POST /api/v1/sensors/reading      X-API-Key: <API_KEY>
{"device_id": "esp32-parking-01",
 "spots": [{"spot_id": "P1", "distance_cm": 23.4, "occupied": true}, ...],
 "gate_car_detected": true, "barrier_state": "closed"}

200 OK
{"barrier_command": "open", "free_spots": 3}
```

### Code layout

```
routers/       HTTP only: parse, validate, call the service
  sensors.py     POST /sensors/reading
  parking.py     GET /spots, POST /barrier/command
services/
  parking.py     ALL business rules (the only place deciding what is written where)
  background.py  periodic jobs
repositories/
  realtime.py    Firebase (live state) + in-memory stand-in
  history.py     MongoDB (history) + in-memory stand-in
schemas/       Pydantic models = the API contract
```

Each repository has an in-memory twin with the same methods, so the business rules are
tested without any network.

### Business rules

- **Validation (422):** unknown spot ID, negative distance, duplicate spot, unknown field,
  malformed JSON. **Security (401):** missing or wrong `X-API-Key` (compared in constant time).
- **Change detection:** the service remembers each spot's last status. Only a real change
  becomes a MongoDB event (`occupancy_events`); a heartbeat just refreshes `last_seen`.
  After a restart, the last states are reloaded from Firebase so nothing is counted twice.
- **One Firebase request per reading:** spots, summary, device and barrier are written with
  a single *multi-path update*.
- **Barrier:** a dashboard command wins and is delivered **once**; otherwise the automatic
  rule answers `open` when a car waits at the gate and a spot is free. Every barrier movement
  is logged in `barrier_events` with its source (`auto`, `dashboard` or `device`).
- **Snapshots:** every minute, the occupancy rate (e.g. 3/4 = 0.75) goes into
  `occupancy_snapshots`, a MongoDB **time-series** collection. This is the series the AI
  learns from. No snapshot is stored while the device is offline, so the data is never made up.
- **Offline detection:** no reading for 15 s â†’ `parking/device/online = false` in Firebase.
- **Resilience:** if MongoDB or Firebase fails, the error is logged but the ESP32 still gets
  its answer.

### Firebase structure

```
parking/
  spots/P1      {status: "free"|"occupied", distance_cm, updated_at}
  summary       {free, occupied, reserved, total}
  device        {online, last_seen, device_id}
  gate_car_detected
barrier/
  state         "closed"|"opening"|"open"|"closing"
  command       {action, source, issued_at, status: "pending"|"delivered"}
```

Security rules (`firebase/database.rules.json`): the browser can **read** everything and
**write** nothing; only the API writes, through the Admin SDK and a service account.

### ESP32 simulator (`tools/esp32_simulator.py`)

Sends exactly the firmware's JSON with random traffic (cars arrive, park, leave) and applies
the barrier commands it receives, so the backend can be demoed without Wokwi:

```powershell
python tools/esp32_simulator.py --api-key <API_KEY> --speed 3
```
```
- car arrived at the gate
  sent: 1/4 occupied, barrier open -> command open, 3 free
- car drove in and parked on P1
  sent: 2/4 occupied, barrier closed -> command none, 2 free
```

### Tests (40, coverage 93%)

| File | Level | What it proves |
|---|---|---|
| `test_parking_service.py` | Unit | change detection, restart, barrier rules, offline, snapshots, resilience |
| `test_api.py` | API | 200 / 202 / 401 / 422 on every endpoint |
| `test_contract.py` | Contract | simulator and API agree with `docs/contracts/sensor-reading.schema.json` |
| `test_integration.py` | Integration | simulated ESP32 â†’ API â†’ real MongoDB (time-series included) |
| `test_realtime_store.py` | Unit | Firebase stand-in behaves like Firebase |

The integration test runs when `TEST_MONGO_URI` is set; CI starts a MongoDB service
container for it.

### Run it

1. Firebase: put the service-account key in `secrets/firebase-service-account.json`
   (git-ignored) and set `FIREBASE_DATABASE_URL` in `.env`.
2. Start the API (`uvicorn app.main:app --reload` in `backend/`), then the simulator.
3. Watch the data arrive live in the Firebase console â†’ Realtime Database, and in
   mongo-express (<http://localhost:8081>).

## Step 4 — Wokwi → API link

**Goal:** the simulated ESP32 sends its reports to the real API over Wi-Fi and obeys the
barrier command in the reply. End-to-end demo: move a slider in Wokwi, the spot turns
`occupied` in Firebase and an event appears in MongoDB.

### How it works

```
Wokwi ESP32 ──Wi-Fi "Wokwi-GUEST"──▶ Wokwi gateway (built into the VS Code extension)
            ──▶ http://host.wokwi.internal:8000 = the API running on this PC
```

The VS Code extension includes Wokwi's *Private IoT Gateway*: the simulated ESP32 reaches
the computer running VS Code under the name `host.wokwi.internal`.

| File | Role |
|---|---|
| `include/ApiLink.h`, `src/ApiLink.cpp` | Wi-Fi connection and `POST /api/v1/sensors/reading`, in a separate FreeRTOS task |
| `include/secrets.example.h` | Wi-Fi name, API URL and API key (defaults for Wokwi) |
| `include/secrets.h` | Your own copy, **git-ignored**. Used instead of the example when it exists |

**Why a separate task?** An HTTP request takes 100 ms to over 1 s (the API waits on
Firebase). If `loop()` made the call, sensing and the servo would freeze for that long.
`ApiLink` runs on core 0, where the Wi-Fi stack already lives, and `loop()` stays on core 1:

```
loop()  ──submit(json)──▶  [report slot: latest only] ──▶ api_link task: POST
loop()  ◀─pollCommand()──  [command queue]            ◀── barrier_command in the reply
```

- **Latest report only.** Every report carries the full state, so when a newer one is ready
  before the previous one was sent, the old one is replaced (`xQueueOverwrite`).
- **Network down = no harm.** The LEDs and the local gate rule keep working. Reports are
  dropped while Wi-Fi or the API is down, and the next heartbeat brings the API up to date.
  Wi-Fi reconnects on its own.
- **Barrier commands.** The reply's `barrier_command` (`open`/`close`) is passed back to
  `loop()`, which calls the barrier state machine. Its safety rule still applies: a `close`
  never comes down on a car.
- **Heartbeat lowered from 5 s to 2 s.** Dashboard commands reach the ESP32 in the reply to
  its next report, so this is the worst-case delay for a manual open/close.
- **Barrier changes are reported right away** (opening, open, closing, closed), so Firebase
  always shows the real barrier position.
- `https://` URLs work too (for the tunnel fallback below); the certificate is not checked.

### Run it

1. **Set the API key.** Copy `firmware/include/secrets.example.h` to
   `firmware/include/secrets.h` and set `API_KEY` to the value of `API_KEY` in `.env`.
2. **Start MongoDB** in the VM (`docker compose up -d mongo mongo-express`), then the API
   on Windows:

   ```powershell
   conda activate smart-parking
   cd backend
   uvicorn app.main:app --port 8000
   ```
3. **Build** the firmware (`pio run` in `firmware/`) and start the simulator
   (`F1` → **Wokwi: Start Simulator**).
4. Expected serial output:

   ```
   [wifi] connecting to Wokwi-GUEST...
   [wifi] connected, IP 10.13.37.2
   [api] 200 in 240 ms -> command none, 4 free
   [spot] P1 -> occupied (23.0 cm), 3/4 free
   [report:change] {"device_id":"esp32-parking-01","spots":[...],...}
   [api] 200 in 210 ms -> command none, 3 free
   ```
   and in the API terminal: `POST /api/v1/sensors/reading HTTP/1.1" 200`.
5. **Check end to end:**
   - Firebase console → Realtime Database: `parking/spots/P1/status` = `occupied`,
     `parking/device/online` = `true`.
   - mongo-express (<http://localhost:8081>) → `occupancy_events`: a new event for P1.
   - Manual command: `POST /api/v1/barrier/command` with `{"action": "open"}` from
     <http://localhost:8000/docs>. Within 2 s the servo opens in Wokwi and the serial
     monitor shows `command open`. It closes again 5 s later (no car at the gate).
   - Stop the simulator: after 15 s `parking/device/online` turns `false`.

### Troubleshooting

| Serial monitor shows | Cause / fix |
|---|---|
| `[api] HTTP 401` | `API_KEY` in `secrets.h` differs from `.env` |
| `[api] HTTP 422: ...` | Report doesn't match the contract (the reply says which field) |
| `[api] unreachable (connection refused)` | API not running, or not on port 8000. Try `uvicorn ... --host 0.0.0.0` and allow it in the Windows firewall |
| `[api] unreachable (...)` with the API running | The gateway can't reach the PC: use the tunnel fallback |
| Stays on `connecting to Wokwi-GUEST...` | Simulator not started from VS Code, or the Wokwi license is not active |

### Fallbacks

- **Tunnel:** run `cloudflared tunnel --url http://localhost:8000` (or `ngrok http 8000`) and
  set `API_URL` in `secrets.h` to `https://<tunnel-host>/api/v1/sensors/reading`.
- **No Wokwi at all:** `python tools/esp32_simulator.py --api-key <API_KEY>` sends the same
  JSON (Step 3).

## Step 5 — Dashboard, reservations and statistics

**Goal:** a React dashboard that shows the parking live, controls the barrier, books spots
and shows statistics computed from the MongoDB history.

### New API endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/reservations` | Active reservations |
| POST | `/api/v1/reservations` | `{"name", "spot_id", "duration_min"}` → 201, or **409** if the spot is occupied / already reserved |
| DELETE | `/api/v1/reservations/{id}` | Cancel → 204, or 404 |
| GET | `/api/v1/stats/occupancy?from&to&step` | Average occupancy rate per bucket of `step` minutes |
| GET | `/api/v1/stats/summary?from&to` | Average occupancy, entries, average parking time, peak hours, weekday × hour heatmap |

`from`/`to` are ISO dates (default: the last 24 h). A date without a time zone is read in
the parking's time zone (`TIMEZONE` in `.env`, e.g. `Africa/Tunis`); statistics are grouped
by **local** hour and weekday.

### Reservation rules (`services/parking.py`)

- The sensors give the *physical* status (free/occupied). A free spot with an active
  reservation is shown **reserved** (orange) and no longer counts as free — so the barrier
  doesn't open for it automatically.
- A spot can't be reserved twice, nor while occupied or before its state is known (409).
- A reservation ends in one of three ways, logged in MongoDB (`reservations` collection):
  **fulfilled** (a car parks on the spot), **cancelled** (dashboard), **expired** (a
  background task checks every 5 s).
- Active reservations live in Firebase (`reservations/{id}`), so the dashboard shows them
  live, and the API reloads them after a restart.

### Statistics (`services/stats.py`, `repositories/history.py`)

The heavy lifting is done by MongoDB **aggregation pipelines** on the time-series collection:
`$dateTrunc` (buckets of N minutes, aligned on local time) and `$isoDayOfWeek` / `$hour`
with a time zone (heatmap). The in-memory twin computes the same results in Python, and an
integration test checks both agree on a real MongoDB.

Entries and average parking time come from `occupancy_events`: each arrival on a spot is
paired with the next departure. Stays that started before the period, or haven't ended,
are left out instead of being guessed.

### Synthetic history (`tools/seed_history.py`)

A live demo only has minutes of data. This script simulates the 4 spots minute by minute
over the past N days (quiet nights, a morning peak, a lunch rush, calmer weekends; average
stays of 45–90 min) and writes exactly what the API would have written. Every document is
tagged `synthetic: true`, and the data stops where real data begins, so the two never mix.

```powershell
python tools/seed_history.py --days 28     # re-running replaces the previous synthetic data
python tools/seed_history.py --clear       # remove it
```

### Dashboard (`frontend/`)

React 18 + Vite, React Router, Tailwind CSS, Recharts, Firebase JS SDK.

| Page | Content |
|---|---|
| **Live map** | SVG plan: green = free, red = occupied, orange = reserved, grey = no signal (always with a text label). "3 / 4 free" counter. Barrier position (animated) and Open / Close buttons. Click a free spot → reservation dialog. |
| **Reservations** | Booking form (name, spot, duration) and the active reservations with a live countdown and Cancel. |
| **Statistics** | Period (24 h / 7 days / 30 days), key figures, occupancy curve, average by hour, weekday × hour heatmap, and the hourly values as a table. |

How the data flows:

```
Live state:  Firebase ──onValue (push, no polling)──▶ dashboard
Actions:     dashboard ──REST──▶ API ──▶ Firebase + MongoDB
Statistics:  dashboard ──REST──▶ API ──aggregation──▶ MongoDB
```

- One Firebase subscription for the whole app (`lib/live.jsx`), shared through a React
  context. Firebase is read-only for the browser and needs only the database URL.
- **Fallback:** with `VITE_FIREBASE_DATABASE_URL` empty, the same data is polled from the
  API every 2 s, so the dashboard works without Firebase.
- The header shows "Sensors online/offline". It also turns offline if `last_seen` is older
  than 20 s, in case the API itself stopped (Firebase would otherwise keep the last value).
- A toast appears when the barrier opens; the occupancy curve leaves a gap where there is
  no data instead of drawing a line across it.

Also fixed in this step: the ESP32 simulator froze when the parking was full and a car was
waiting at the gate (no car could leave any more).

### Run it

1. **Publish the Firebase security rules** (once): Firebase console → Realtime Database →
   *Rules*, paste the content of `firebase/database.rules.json`, click **Publish**.
   Without it the dashboard shows `permission_denied`.
2. `.env` (repo root) needs `TIMEZONE`, `VITE_API_URL` and `VITE_FIREBASE_DATABASE_URL`
   (see `.env.example`).
3. Start MongoDB (VM) and the API (`uvicorn app.main:app --port 8000` in `backend/`).
4. Seed the history once: `python tools/seed_history.py --days 28`
5. Start the dashboard:

   ```powershell
   cd frontend
   npm install
   npm run dev          # http://localhost:5173
   ```
6. Start Wokwi (or `python tools/esp32_simulator.py --api-key <API_KEY> --speed 0.3`).

### Tests (75, coverage 90%)

New: `test_reservations.py` (rules + 409/404/422), `test_stats.py` (buckets, local time,
peak hours, parking time, parameter validation), and a MongoDB integration test of the
aggregation pipelines and the reservation log. CI now also builds the dashboard.

## Step 6 — Accounts, prepaid wallet, gate access and the assistant

**Goal:** every driver has an account (with a UID) and a prepaid wallet; the barrier only
opens for identified users with credit; and a chatbot at the gate and in the app understands
English, French and Arabic (Tunisian Darija too), by text or by voice.

### What was done

- **Accounts** (`/auth/register`, `/auth/login`, `/me`): each account gets a UID such as
  `SP-7KQ2M9XA`. Passwords are hashed with scrypt; sessions are signed tokens (JWT).
- **Prepaid wallet** (amounts in millimes, never floats): top-ups through a **simulated card
  gateway** (`/payments/checkout` then `/payments/{id}/confirm`, Luhn check, receipts; only
  the brand and last 4 digits are stored). Every balance change writes a statement line.

  | Test card | Result |
  |---|---|
  | 4242 4242 4242 4242 | success (Visa) |
  | 5555 5555 5555 4444 | success (Mastercard) |
  | 4000 0000 0000 0002 | declined |
  | 4000 0000 0000 9995 | insufficient funds |

- **Rules** (`GATE_MODE=account`): entering needs at least `MIN_ENTRY_BALANCE` and no debt,
  plus a free spot or your own reservation. Leaving is always allowed and charges the stay
  (first 15 min free, then per started 15 min at `HOURLY_RATE`); it may end in a negative
  balance, which **blocks entry and reservations until the user tops up**. Reservations need
  an account and cost `RESERVATION_FEE` (refunded if cancelled).
- **Gate kiosk** (`/gate` page): the app shows a QR code (and 6 digits) valid 2 minutes; the
  kiosk scans it with the camera and opens a 10-minute kiosk session for that driver. Kiosk
  sessions can open the gate and reserve, but cannot pay or change the profile. Wrong codes
  are limited to 5 per minute.
- **Assistant** (`POST /api/v1/chat`): chat widget on every page, full-screen on the kiosk.
  Voice uses the browser's speech recognition (Chrome/Edge: en-US, fr-FR, ar-TN) and replies
  can be read aloud. Two engines share the same tools (spots, prices, busy hours, account,
  reserve, cancel, open gate, top-up), so the same rules apply:
  - **Claude** when `ANTHROPIC_API_KEY` is set: free-form understanding in any of the three
    languages. The conversation is append-only (who is speaking is added as a system message),
    which keeps the prompt cache warm. Card details are never asked for in the chat: the
    assistant opens the secure checkout instead.
  - **Offline rules** otherwise, or if the Claude API fails: keywords in EN / FR / Arabic /
    Darija (Arabic letters or Latin with digits, e.g. "7ell el bab").
- **Firmware:** in account mode the ESP32 no longer opens on its own; it waits for the API's
  command. If the API stays silent for 10 s it goes back to the local rule, so a network
  failure never locks the parking.

### Run it

Add to `.env` (see `.env.example`): `GATE_MODE=account`, a long random `JWT_SECRET`, and
optionally `ANTHROPIC_API_KEY`. Start the API and the dashboard as in Step 5, then:

1. **Sign in** → create an account → **Top up** with a test card.
2. Open **Gate kiosk**, type the 6 digits shown on your Account page (or scan the QR code).
3. Say or type "حل الباب", "Ouvrez la barrière" or "open the gate" → the barrier opens on the
   next ESP32 heartbeat. "Je pars" / "I'm leaving" / "باش نخرج" charges the stay and opens it.

`GET /api/v1/chat/info` says which engine is answering (`claude` or `rules`).
