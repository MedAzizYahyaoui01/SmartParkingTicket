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
    app_version: str = "0.1.0"

    # MongoDB (occupancy history)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "smart_parking"

    # Shared secret the ESP32 sends in the X-API-Key header
    api_key: str = "change-me"

    # Comma-separated list of origins allowed to call the API from a browser
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
