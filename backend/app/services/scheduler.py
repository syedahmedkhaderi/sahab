"""GPU scheduler service.

Atomic GPU leasing with Redis lock + Postgres row update,
FIFO queue via Redis list, CPU fallback, assign-on-free.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GpuInventory, GpuLease, GpuStatus, Session, SessionState
from app.services import gpu_probe

logger = logging.getLogger(__name__)

# Redis key constants
REDIS_GPU_LOCK = "sahab:gpu_lock"
REDIS_GPU_QUEUE = "sahab:gpu_queue"
LEASE_LOCK_TTL_SECONDS = 10  # hold the distributed lock for at most 10 s


class GpuBusyError(Exception):
    """Every GPU the DB calls free is in fact running work started outside Sahab."""


async def _acquire_redis_lock(redis: Redis, lock_key: str, ttl: int) -> bool:
    """Try to acquire a Redis SET NX PX lock. Returns True if acquired."""
    result = await redis.set(lock_key, "1", nx=True, px=ttl * 1000)
    return result is True


async def _release_redis_lock(redis: Redis, lock_key: str) -> None:
    await redis.delete(lock_key)


async def _pick_idle_gpu(candidates: list[GpuInventory]) -> GpuInventory | None:
    """
    Choose a candidate that is genuinely idle on the host.

    The DB status only reflects Sahab's own leases, so a GPU can read as free
    while another job holds its memory. Cross-check the live DCGM readings and
    pick the quietest GPU that clears both thresholds.

    If the probe is unavailable the DB status is all we have — return the first
    candidate rather than blocking every launch on a monitoring outage.
    """
    settings = get_settings()
    readings = await gpu_probe.get_gpu_readings(settings.dcgm_metrics_url)
    if readings is None:
        return candidates[0]

    idle = []
    for gpu in candidates:
        reading = readings.get(gpu.gpu_uuid)
        if reading is None:
            # Not in the scrape at all: no evidence it is busy, so still usable.
            idle.append((0.0, 0.0, gpu))
            continue
        if reading.is_busy(settings.busy_vram_mb, settings.busy_util_pct):
            logger.info(
                "Skipping GPU %s: %.0f%% util, %.0f MB in use by an external job",
                gpu.gpu_uuid, reading.util_pct, reading.used_mb,
            )
            continue
        idle.append((reading.used_mb, reading.util_pct, gpu))

    if not idle:
        return None

    idle.sort(key=lambda row: (row[0], row[1]))
    return idle[0][2]


async def try_lease_gpu(
    session_id: str,
    db: AsyncSession,
    redis: Redis,
) -> str | None:
    """
    Atomically attempt to lease a free GPU for the given session.

    Steps:
      1. Acquire a short-lived Redis lock to serialise concurrent callers.
      2. Inside the lock, SELECT every GPU the DB calls free.
      3. Drop the ones a live probe shows are busy with outside work.
      4. UPDATE the quietest one to 'leased' in Postgres.
      5. INSERT a gpu_lease row, then release the lock.

    Returns the gpu_uuid on success, or None if the pool holds no free GPU.
    Raises GpuBusyError when GPUs are free in the DB but all busy on the host —
    a distinct situation, and one worth telling the user about in those terms.
    """
    acquired = await _acquire_redis_lock(redis, REDIS_GPU_LOCK, LEASE_LOCK_TTL_SECONDS)
    if not acquired:
        # Another caller holds the lock; wait briefly and retry once
        await asyncio.sleep(0.2)
        acquired = await _acquire_redis_lock(redis, REDIS_GPU_LOCK, LEASE_LOCK_TTL_SECONDS)
        if not acquired:
            return None

    try:
        result = await db.execute(
            select(GpuInventory)
            .where(GpuInventory.status == GpuStatus.free)
            .with_for_update(skip_locked=True)
        )
        candidates = list(result.scalars().all())
        if not candidates:
            return None

        gpu = await _pick_idle_gpu(candidates)
        if gpu is None:
            # Free on paper, all busy in reality — a different problem from an
            # empty pool, and the caller says so in different words.
            raise GpuBusyError(
                "All free GPUs are running work started outside Sahab"
            )

        # Mark leased in inventory
        await db.execute(
            update(GpuInventory)
            .where(GpuInventory.gpu_uuid == gpu.gpu_uuid)
            .values(status=GpuStatus.leased)
        )

        # Create lease record
        lease = GpuLease(
            session_id=session_id,
            gpu_uuid=gpu.gpu_uuid,
        )
        db.add(lease)
        await db.flush()

        logger.info("Leased GPU %s to session %s", gpu.gpu_uuid, session_id)
        return gpu.gpu_uuid

    finally:
        await _release_redis_lock(redis, REDIS_GPU_LOCK)


async def release_gpu(
    session_id: str,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Close the open GPU lease for a session and mark the GPU free."""
    # Find the open lease (ended_at is NULL)
    result = await db.execute(
        select(GpuLease).where(
            GpuLease.session_id == session_id,
            GpuLease.ended_at.is_(None),
        )
    )
    lease = result.scalar_one_or_none()
    if lease is None:
        logger.warning("No open lease found for session %s", session_id)
        return

    now = datetime.now(tz=timezone.utc)
    await db.execute(
        update(GpuLease)
        .where(GpuLease.id == lease.id)
        .values(ended_at=now)
    )

    await db.execute(
        update(GpuInventory)
        .where(GpuInventory.gpu_uuid == lease.gpu_uuid)
        .values(status=GpuStatus.free)
    )

    await db.flush()
    logger.info("Released GPU %s from session %s", lease.gpu_uuid, session_id)

    # Trigger queue drain so the next queued session gets the GPU
    await _notify_queue(redis)


async def enqueue_session(session_id: str, redis: Redis) -> int:
    """Push a session onto the FIFO GPU queue. Returns queue length (1-indexed position)."""
    await redis.rpush(REDIS_GPU_QUEUE, session_id)
    length = await redis.llen(REDIS_GPU_QUEUE)
    return int(length)


async def dequeue_next_session(redis: Redis) -> str | None:
    """Pop the next queued session_id from the front of the queue."""
    value = await redis.lpop(REDIS_GPU_QUEUE)
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


async def get_queue_position(session_id: str, redis: Redis) -> int | None:
    """Return the 1-based queue position of a session, or None if not queued."""
    items = await redis.lrange(REDIS_GPU_QUEUE, 0, -1)
    for i, item in enumerate(items, start=1):
        sid = item.decode() if isinstance(item, bytes) else item
        if sid == session_id:
            return i
    return None


async def _notify_queue(redis: Redis) -> None:
    """Publish a message to signal the worker to drain the queue."""
    await redis.publish("sahab:queue_event", "gpu_freed")


async def drain_queue(db: AsyncSession, redis: Redis) -> None:
    """
    Worker-side: pop queued sessions and try to assign them freed GPUs.

    Called by the scheduler worker after a GPU is released.
    Imports sessions service lazily to avoid circular imports.
    """
    from app.services import sessions as sessions_svc  # noqa: PLC0415

    while True:
        # Peek at the front without popping
        items = await redis.lrange(REDIS_GPU_QUEUE, 0, 0)
        if not items:
            break

        session_id = items[0].decode() if isinstance(items[0], bytes) else items[0]

        # Try to lease a GPU for this session
        try:
            gpu_uuid = await try_lease_gpu(session_id, db, redis)
        except GpuBusyError:
            # Leave the session queued; the next release retries the drain.
            logger.info("Queue drain paused: every free GPU is externally busy")
            break
        if gpu_uuid is None:
            # No GPU available yet; stop draining
            break

        # GPU leased — pop it from the queue and advance the session
        await redis.lpop(REDIS_GPU_QUEUE)

        # Update the session state to starting and record the GPU
        await sessions_svc.advance_to_starting(session_id, gpu_uuid, db, redis)

        logger.info("Queue drain: assigned GPU %s to queued session %s", gpu_uuid, session_id)
