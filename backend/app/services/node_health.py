"""Keep the node registry honest about which machines are actually there.

Run every minute by the worker. Its whole job is to notice a machine that has
stopped answering before a user does, and to make sure nothing is stranded when
one dies:

* a GPU on a dead machine must leave the pool, or the next launch is placed
  somewhere it cannot start;
* a session running on a dead machine must be failed and its lease released, or
  that GPU is held hostage until someone notices by hand;
* metering must stop, which it does on its own once the session leaves 'running'.

A short outage is not treated as a death. Nothing is torn down until a machine
has been unreachable for NODE_UNREACHABLE_GRACE_SECONDS (5 minutes by default),
because a dockerd restart or a blip on the network is far more common than a VM
actually going away, and failing someone's work over five seconds of packet loss
would be worse than the outage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    GpuInventory,
    GpuLease,
    GpuStatus,
    Node,
    NodeStatus,
    Session,
    SessionState,
)
from app.services import nodes as nodes_svc
from app.services import scheduler as scheduler_svc

logger = logging.getLogger(__name__)

_LIVE_STATES = (SessionState.starting, SessionState.running, SessionState.stopping)


async def check_all_nodes(db: AsyncSession, redis: Redis, settings: Settings) -> None:
    """Probe every node, then act on the ones that have been gone too long."""
    nodes = (await db.execute(select(Node))).scalars().all()

    for node in nodes:
        # A machine that has never enrolled has nothing to probe: no certificate
        # was issued for it, and it is waiting on someone to run the join
        # command, not on us. Probing it every minute would only mislabel it.
        if node.enrolled_at is None:
            continue

        reachable, detail = await nodes_svc.ping_node(node)
        was_ready = node.status == NodeStatus.ready
        await nodes_svc.record_health(db, node, reachable, detail)

        if reachable:
            if not was_ready:
                await _restore_node(db, node)
            continue

        if node.status != NodeStatus.unreachable:
            # Draining or disabled by an admin: leave it alone.
            continue

        since = node.unreachable_since
        if since is None:
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        grace = timedelta(seconds=settings.node_unreachable_grace_seconds)
        if datetime.now(tz=timezone.utc) - since < grace:
            continue

        await _evacuate_node(db, redis, node)

    await db.commit()


async def _restore_node(db: AsyncSession, node: Node) -> None:
    """Put a recovered machine's GPUs back in the pool.

    Only GPUs with no open lease are freed. One that still has an open lease
    belongs to a session that survived the outage, and marking it free would let
    a second user be placed on the same card.
    """
    gpus = (
        await db.execute(
            select(GpuInventory).where(
                GpuInventory.node_id == node.id,
                GpuInventory.status == GpuStatus.disabled,
            )
        )
    ).scalars().all()

    restored = 0
    for gpu in gpus:
        open_lease = (
            await db.execute(
                select(GpuLease).where(
                    GpuLease.gpu_uuid == gpu.gpu_uuid,
                    GpuLease.ended_at.is_(None),
                )
            )
        ).scalars().first()
        if open_lease is not None:
            continue
        gpu.status = GpuStatus.free
        restored += 1

    if restored:
        logger.info("Node %s recovered: %d GPU(s) back in the pool", node.name, restored)
    await db.flush()


async def _evacuate_node(db: AsyncSession, redis: Redis, node: Node) -> None:
    """A machine has been gone long enough. Take it out and free what it held."""
    gpus = (
        await db.execute(select(GpuInventory).where(GpuInventory.node_id == node.id))
    ).scalars().all()

    sessions = (
        await db.execute(
            select(Session).where(
                Session.node_id == node.id,
                Session.state.in_(_LIVE_STATES),
            )
        )
    ).scalars().all()

    if not sessions and all(g.status == GpuStatus.disabled for g in gpus):
        return  # already evacuated; nothing new to do

    logger.warning(
        "Node %s has been unreachable past the grace period; failing %d session(s) "
        "and taking %d GPU(s) out of the pool",
        node.name, len(sessions), len(gpus),
    )

    now = datetime.now(tz=timezone.utc)
    for session in sessions:
        session.state = SessionState.failed
        session.ended_at = now
        # Release before disabling the GPU: release_gpu sets it back to free, so
        # doing it the other way round would undo the disable.
        try:
            await scheduler_svc.release_gpu(session.id, db, redis)
        except Exception:
            logger.exception("Could not release the GPU lease for session %s", session.id)

    for gpu in gpus:
        # Leave a leased GPU alone only if its session is still live elsewhere,
        # which cannot happen here — every live session on this node was just
        # failed and released above.
        gpu.status = GpuStatus.disabled

    await db.flush()
