import asyncio
import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.config import Settings, get_settings
from app.ml.predictor import ModelStore
from app.repositories.accounts import AccountRepository, MongoAccountRepository
from app.repositories.history import HistoryRepository, MongoHistoryRepository
from app.repositories.realtime import RealtimeStore, build_realtime_store
from app.routers import (
    accounts,
    chat,
    gate,
    health,
    parking,
    payments,
    predictions,
    reservations,
    sensors,
    stats,
)
from app.services.accounts import AccountService, UserNotFoundError
from app.services.assistant.claude import ClaudeEngine
from app.services.assistant.service import AssistantService
from app.services.background import run_periodically
from app.services.gate import GateService
from app.services.parking import ParkingService
from app.services.payments import PaymentService
from app.services.predictions import PredictionService
from app.services.stats import StatsService

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(
    settings: Settings | None = None,
    store: RealtimeStore | None = None,
    history: HistoryRepository | None = None,
    account_repo: AccountRepository | None = None,
    claude_client: anthropic.AsyncAnthropic | None = None,
    background_tasks: bool = True,
) -> FastAPI:
    """Builds the app. Tests pass in-memory stores (and a fake Claude client) and turn
    background tasks off."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_mongo = history is None or account_repo is None
        if owns_mongo:
            db.connect(settings.mongo_uri)
        history_repo = history or MongoHistoryRepository(db.get_db(settings.mongo_db))
        accounts_repo = account_repo or MongoAccountRepository(db.get_db(settings.mongo_db))
        realtime = store or build_realtime_store(
            settings.firebase_database_url, settings.firebase_credentials
        )

        service = ParkingService(realtime, history_repo, settings)
        await service.startup()
        app.state.parking = service
        app.state.stats = StatsService(history_repo, settings.timezone)
        app.state.predictions = PredictionService(
            history_repo, ModelStore(settings.model_path), len(settings.spot_ids)
        )

        account_service = AccountService(accounts_repo, service, settings)
        try:
            await account_service.startup()
        except Exception:
            logger.exception("Could not prepare the accounts collections")
        app.state.accounts = account_service
        app.state.gate = GateService(account_service, service)
        app.state.payments = PaymentService(account_service)
        app.state.assistant = AssistantService(
            service,
            account_service,
            app.state.gate,
            app.state.stats,
            _claude_engine(settings, claude_client),
        )
        logger.info("Assistant engine: %s", app.state.assistant.engine_name)

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

    @app.exception_handler(UserNotFoundError)
    async def deleted_account(request: Request, exc: UserNotFoundError) -> JSONResponse:
        # A valid token whose account no longer exists
        return JSONResponse(
            {"detail": "Account not found, please sign in again"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    app.include_router(health.router)
    for router in (
        sensors,
        parking,
        reservations,
        stats,
        predictions,
        accounts,
        payments,
        gate,
        chat,
    ):
        app.include_router(router.router, prefix="/api/v1")
    return app


def _claude_engine(
    settings: Settings, client: anthropic.AsyncAnthropic | None
) -> ClaudeEngine | None:
    """Claude when asked for (or in "auto" mode when an API key is set), else None: the
    assistant then answers with the offline rules."""
    if settings.chat_engine == "rules":
        return None
    if client is None:
        if settings.chat_engine == "auto" and not settings.anthropic_api_key:
            return None
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None, timeout=30.0, max_retries=1
        )
    return ClaudeEngine(client, settings.chat_model)


app = create_app()
