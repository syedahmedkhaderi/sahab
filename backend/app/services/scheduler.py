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

from app.models import GpuInventory, GpuLease, GpuStatus, Session, SessionState

logger = logging.getLogger(__name__)

# Redis key constants
REDIS_GPU_LOCK = "sahab:gpu_lock"
REDIS_GPU_QUEUE = "sahab:gpu_queue"
LEASE_LOCK_TTL_SECONDS = 10  # hold the distributed lock for at most 10 s


async def _acquire_redis_lock(redis: Redis, lock_key: str, ttl: int) -> bool:
    """Try to acquire a Redis SET NX PX lock. Returns True if acquired."""
    result = await redis.set(lock_key, "1", nx=True, px=ttl * 1000)
    return result is True


async def _release_redis_lock(redis: Redis, lock_key: str) -> None:
    await redis.delete(lock_key)


async def try_lease_gpu(
    session_id: str,
    db: AsyncSession,
    redis: Redis,
) -> str | None:
    """
    Atomically attempt to lease a free GPU for the given session.

    Steps:
      1. Acquire a short-lived Redis lock to serialise concurrent callers.
      2. Inside the lock, SELECT a free GPU row.
      3. UPDATE it to 'leased' in Postgres.
      4. INSERT a gpu_lease row.
      5. Release the lock.

    Returns the gpu_uuid on success, None if no GPU is free.
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
            .limit(1)
        )
        gpu = result.scalar_one_or_none()
        if gpu is None:
            return None

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
        gpu_uuid = await try_lease_gpu(session_id, db, redis)
        if gpu_uuid is None:
            # No GPU available yet; stop draining
            break

        # GPU leased — pop it from the queue and advance the session
        await redis.lpop(REDIS_GPU_QUEUE)

        # Update the session state to starting and record the GPU
        await sessions_svc.advance_to_starting(session_id, gpu_uuid, db, redis)

        logger.info("Queue drain: assigned GPU %s to queued session %s", gpu_uuid, session_id)
