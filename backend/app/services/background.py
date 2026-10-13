"""Periodic jobs that run inside the API process."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def run_periodically(interval_s: float, job: Callable[[], Awaitable[object]]) -> None:
    """Runs `job` every `interval_s` seconds until cancelled; one failure never stops the loop."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic job %s failed", getattr(job, "__name__", job))
