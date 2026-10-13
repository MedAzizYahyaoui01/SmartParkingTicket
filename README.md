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
| 27017 | 27017 | MongoDB |
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
