"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # One .env at the repo root is shared by Docker Compose and the API run locally
    # from backend/; a backend/.env, if present, takes precedence.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Smart Parking API"
    app_version: str = "0.4.0"

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

    # Gate access. "auto": the barrier opens for any car when a spot is free (the ESP32 rule).
    # "account": it opens only for a signed-in user with enough credit (app, kiosk or chat).
    gate_mode: Literal["auto", "account"] = "auto"

    # Accounts. Tokens are signed with this secret: set a long random value in production.
    jwt_secret: str = "change-me-to-a-long-random-string"
    token_ttl_h: int = 24 * 7
    kiosk_token_ttl_min: int = 10  # session opened at the gate by scanning the QR code
    access_code_ttl_s: int = 120  # lifetime of the 6-digit code behind the QR code

    # Prepaid wallet. Amounts are integers in millimes (1 TND = 1000 millimes).
    currency: str = "TND"
    hourly_rate: int = 2000
    free_minutes: int = 15  # the first minutes of a stay are free
    billing_block_min: int = 15  # after that, every started block is charged
    reservation_fee: int = 500
    min_entry_balance: int = 1000  # credit needed to enter
    topup_min: int = 5000
    topup_max: int = 500_000

    # Assistant. "auto" uses Claude when an API key is set, the offline rules otherwise.
    chat_engine: Literal["auto", "claude", "rules"] = "auto"
    anthropic_api_key: str = ""
    chat_model: str = "claude-opus-5-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
