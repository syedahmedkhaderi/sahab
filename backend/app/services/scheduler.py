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
from typing import NamedTuple

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    GpuInventory,
    GpuLease,
    GpuStatus,
    Node,
    NodeStatus,
    Session,
    SessionState,
)
from app.services import gpu_probe

logger = logging.getLogger(__name__)

# Redis key constants
REDIS_GPU_LOCK = "sahab:gpu_lock"
REDIS_GPU_QUEUE = "sahab:gpu_queue"
LEASE_LOCK_TTL_SECONDS = 10  # hold the distributed lock for at most 10 s


class GpuBusyError(Exception):
    """Every GPU the DB calls free is in fact running work started outside Sahab."""


class Lease(NamedTuple):
    """A leased GPU and the machine it lives in.

    The node is not decoration: the GPU UUID alone is meaningless to a container
    started on a different machine, so the two always travel together.
    """

    gpu_uuid: str
    node_name: str
    node_id: str


async def _acquire_redis_lock(redis: Redis, lock_key: str, ttl: int) -> bool:
    """Try to acquire a Redis SET NX PX lock. Returns True if acquired."""
    result = await redis.set(lock_key, "1", nx=True, px=ttl * 1000)
    return result is True


async def _release_redis_lock(redis: Redis, lock_key: str) -> None:
    await redis.delete(lock_key)


def _node_metrics_url(node: Node, settings) -> str:
    """Where to scrape a node's DCGM exporter.

    A node registers its own URL at enrollment. The manager predates nodes and
    normally has none, so it falls back to DCGM_METRICS_URL — the compose-network
    address that already worked when this was a one-machine platform.
    """
    if node.metrics_url:
        return node.metrics_url
    return settings.dcgm_metrics_url


async def _pick_idle_gpu(
    candidates: list[tuple[GpuInventory, Node]],
) -> tuple[GpuInventory, Node] | None:
    """
    Choose a candidate that is genuinely idle on its own host.

    The DB status only reflects Sahab's own leases, so a GPU can read as free
    while another job holds its memory. Cross-check the live DCGM readings and
    pick the quietest GPU that clears both thresholds.

    Each node has its own exporter, so this scrapes one URL per node rather than
    one for the cluster — reading node A's numbers for node B's GPUs would place
    work on a card that is already busy.

    A node whose probe is unavailable is not excluded: its GPUs stay eligible but
    rank behind any GPU we can positively confirm is idle. That keeps the original
    fail-open promise (a monitoring outage never blocks a launch) while preferring
    the evidence we do have.
    """
    settings = get_settings()

    urls = {_node_metrics_url(node, settings) for _, node in candidates}
    readings_by_url: dict[str, dict[str, gpu_probe.GpuReading] | None] = {}
    for url in urls:
        readings_by_url[url] = await gpu_probe.get_gpu_readings(url)

    CONFIRMED_IDLE, UNKNOWN = 0, 1
    ranked: list[tuple[int, float, float, GpuInventory, Node]] = []

    for gpu, node in candidates:
        readings = readings_by_url.get(_node_metrics_url(node, settings))
        if readings is None:
            # Probe down for this node: no evidence either way.
            ranked.append((UNKNOWN, 0.0, 0.0, gpu, node))
            continue

        reading = readings.get(gpu.gpu_uuid)
        if reading is None:
            # Not in this node's scrape at all: no evidence it is busy.
            ranked.append((UNKNOWN, 0.0, 0.0, gpu, node))
            continue

        if reading.is_busy(settings.busy_vram_mb, settings.busy_util_pct):
            logger.info(
                "Skipping GPU %s on %s: %.0f%% util, %.0f MB in use by an external job",
                gpu.gpu_uuid, node.name, reading.util_pct, reading.used_mb,
            )
            continue

        ranked.append((CONFIRMED_IDLE, reading.used_mb, reading.util_pct, gpu, node))

    if not ranked:
        return None

    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    chosen = ranked[0]
    return chosen[3], chosen[4]


async def try_lease_gpu(
    session_id: str,
    db: AsyncSession,
    redis: Redis,
) -> Lease | None:
    """
    Atomically attempt to lease a free GPU for the given session.

    Steps:
      1. Acquire a short-lived Redis lock to serialise concurrent callers.
      2. Inside the lock, SELECT every free GPU that sits in a node accepting work.
      3. Drop the ones a live probe shows are busy with outside work.
      4. UPDATE the quietest one to 'leased' in Postgres.
      5. INSERT a gpu_lease row, then release the lock.

    Returns a Lease (GPU + the machine it is in) on success, or None if the pool
    holds no free GPU. Raises GpuBusyError when GPUs are free in the DB but all
    busy on their hosts — a distinct situation, and one worth telling the user
    about in those terms.

    Only nodes in state 'ready' are considered. 'draining' keeps its running
    sessions but takes no new ones, which is how a machine is retired without
    interrupting anyone; 'unreachable' and 'disabled' are out entirely.
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
            select(GpuInventory, Node)
            .join(Node, GpuInventory.node_id == Node.id)
            .where(
                GpuInventory.status == GpuStatus.free,
                Node.status == NodeStatus.ready,
            )
            .with_for_update(of=GpuInventory, skip_locked=True)
        )
        candidates = [(gpu, node) for gpu, node in result.all()]
        if not candidates:
            return None

        picked = await _pick_idle_gpu(candidates)
        if picked is None:
            # Free on paper, all busy in reality — a different problem from an
            # empty pool, and the caller says so in different words.
            raise GpuBusyError(
                "All free GPUs are running work started outside Sahab"
            )
        gpu, node = picked

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

        logger.info(
            "Leased GPU %s on node %s to session %s", gpu.gpu_uuid, node.name, session_id
        )
        return Lease(gpu_uuid=gpu.gpu_uuid, node_name=node.name, node_id=node.id)

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
            lease = await try_lease_gpu(session_id, db, redis)
        except GpuBusyError:
            # Leave the session queued; the next release retries the drain.
            logger.info("Queue drain paused: every free GPU is externally busy")
            break
        if lease is None:
            # No GPU available yet; stop draining
            break

        # GPU leased — pop it from the queue and advance the session
        await redis.lpop(REDIS_GPU_QUEUE)

        # Update the session state to starting and record the GPU
        await sessions_svc.advance_to_starting(session_id, lease, db, redis)

        logger.info(
            "Queue drain: assigned GPU %s on %s to queued session %s",
            lease.gpu_uuid, lease.node_name, session_id,
        )
