"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # One .env at the repo root is shared by Docker Compose and the API run locally
    # from backend/; a backend/.env, if present, takes precedence.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Smart Parking API"
    app_version: str = "0.3.0"

    # MongoDB (occupancy history)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "smart_parking"

    # Firebase Realtime Database (live state). If either is empty, the API keeps the
    # live state in memory instead — handy for tests and offline development.
    firebase_database_url: str = ""
    firebase_credentials: str = ""

    # Shared secret the ESP32 sends in the X-API-Key header
    api_key: str = "change-me"

    # Comma-separated list of origins allowed to call the API from a browser
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Parking layout and timings
    spot_ids: list[str] = ["P1", "P2", "P3", "P4"]
    device_offline_after_s: int = 15
    snapshot_interval_s: int = 60

    # Reservations (simulated): a reserved spot is held for this long, then released
    reservation_default_min: int = 15
    reservation_max_min: int = 60

    # Time zone of the parking: statistics are grouped by *local* hour and weekday
    timezone: str = "UTC"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
