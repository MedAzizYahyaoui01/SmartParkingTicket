import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import Settings, get_settings
from app.repositories.history import HistoryRepository, MongoHistoryRepository
from app.repositories.realtime import RealtimeStore, build_realtime_store
from app.routers import health, parking, reservations, sensors, stats
from app.services.background import run_periodically
from app.services.parking import ParkingService
from app.services.stats import StatsService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(
    settings: Settings | None = None,
    store: RealtimeStore | None = None,
    history: HistoryRepository | None = None,
    background_tasks: bool = True,
) -> FastAPI:
    """Builds the app. Tests pass in-memory stores and turn background tasks off."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_mongo = history is None
        if owns_mongo:
            db.connect(settings.mongo_uri)
        history_repo = history or MongoHistoryRepository(db.get_db(settings.mongo_db))
        realtime = store or build_realtime_store(
            settings.firebase_database_url, settings.firebase_credentials
        )

        service = ParkingService(realtime, history_repo, settings)
        await service.startup()
        app.state.parking = service
        app.state.stats = StatsService(history_repo, settings.timezone)

        tasks = []
        if background_tasks:
            tasks = [
                asyncio.create_task(run_periodically(5, service.check_device_online)),
                asyncio.create_task(run_periodically(5, service.expire_reservations)),
                asyncio.create_task(
                    run_periodically(settings.snapshot_interval_s, service.take_snapshot)
                ),
            ]
        yield
        for task in tasks:
            task.cancel()
        if owns_mongo:
            await db.close()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(sensors.router, prefix="/api/v1")
    app.include_router(parking.router, prefix="/api/v1")
    app.include_router(reservations.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    return app


app = create_app()
