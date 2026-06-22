"""
Sahab background worker — APScheduler driving metering and queue drain.

Run as: python -m app.worker

Two jobs:
  - meter_tick  : every 60 s — deduct credits for all running sessions.
  - queue_tick  : every 30 s — try to promote queued sessions when GPUs free.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis

from app.config import get_settings
from app.db import AsyncSessionLocal, engine, Base
from app.services.jupyterhub import JupyterHubClient
from app.services.metering import meter_active_sessions
from app.services.scheduler import drain_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


async def meter_tick() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    hub = JupyterHubClient(settings)
    try:
        async with AsyncSessionLocal() as db:
            await meter_active_sessions(db=db, redis=redis, settings=settings, hub=hub)
    except Exception as exc:
        logger.error("meter_tick error: %s", exc, exc_info=True)
    finally:
        await redis.aclose()


async def queue_tick() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        async with AsyncSessionLocal() as db:
            await drain_queue(db=db, redis=redis)
            await db.commit()
    except Exception as exc:
        logger.error("queue_tick error: %s", exc, exc_info=True)
    finally:
        await redis.aclose()


async def main() -> None:
    logger.info("Sahab worker starting...")

    # Ensure tables exist (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(meter_tick, "interval", seconds=60, id="meter", max_instances=1)
    scheduler.add_job(queue_tick, "interval", seconds=30, id="queue", max_instances=1)
    scheduler.start()

    logger.info("Worker running. Jobs: meter (60 s), queue drain (30 s). Press Ctrl+C to stop.")

    stop_event = asyncio.Event()

    def _handle_signal(sig, frame):  # noqa: ANN001
        logger.info("Signal %s received, shutting down worker", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    await stop_event.wait()
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
