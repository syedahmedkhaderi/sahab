"""Tests: GPU lease atomicity, no double-allocation, queue, CPU fallback."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis as fakeredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GpuInventory, GpuLease, GpuStatus, Session, SessionState, ResourceType
from app.services.scheduler import (
    enqueue_session,
    get_queue_position,
    release_gpu,
    try_lease_gpu,
)
from app.services.credits import grant_credits


async def _make_session(db: AsyncSession, user_id: str) -> Session:
    session = Session(
        user_id=user_id,
        resource_type=ResourceType.l4_gpu,
        state=SessionState.starting,
    )
    db.add(session)
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_lease_gpu_success(
    db_session: AsyncSession,
    gpu_inventory: list[GpuInventory],
    active_user,
) -> None:
    """try_lease_gpu should return a GPU UUID when one is free."""
    redis = fakeredis.FakeRedis()
    session = await _make_session(db_session, active_user.id)

    gpu_uuid = await try_lease_gpu(session.id, db_session, redis)
    assert gpu_uuid is not None
    assert gpu_uuid in [g.gpu_uuid for g in gpu_inventory]

    await redis.aclose()


@pytest.mark.asyncio
async def test_no_double_allocation(
    db_session: AsyncSession,
    gpu_inventory: list[GpuInventory],
    active_user,
) -> None:
    """
    Two concurrent lease attempts must not assign the same GPU to two sessions.

    This is the core safety test for whole-GPU allocation.
    """
    redis = fakeredis.FakeRedis()
    s1 = await _make_session(db_session, active_user.id)
    s2 = await _make_session(db_session, active_user.id)
    s3 = await _make_session(db_session, active_user.id)

    # Only 2 GPUs available — all 3 race simultaneously
    results = await asyncio.gather(
        try_lease_gpu(s1.id, db_session, redis),
        try_lease_gpu(s2.id, db_session, redis),
        try_lease_gpu(s3.id, db_session, redis),
    )

    # Exactly 2 should succeed (matching the 2 GPUs)
    successful = [r for r in results if r is not None]
    assert len(successful) == 2, f"Expected 2 leases, got {len(successful)}: {results}"
    # No duplicate GPU UUIDs
    assert len(set(successful)) == 2, "Same GPU was assigned to two sessions!"

    await redis.aclose()


@pytest.mark.asyncio
async def test_lease_returns_none_when_all_busy(
    db_session: AsyncSession,
    gpu_inventory: list[GpuInventory],
    active_user,
) -> None:
    """When all GPUs are leased, try_lease_gpu returns None."""
    redis = fakeredis.FakeRedis()

    sessions = []
    for _ in range(len(gpu_inventory)):
        s = await _make_session(db_session, active_user.id)
        sessions.append(s)
        uuid = await try_lease_gpu(s.id, db_session, redis)
        assert uuid is not None  # sanity: first N should succeed

    # Now a third request should fail
    extra = await _make_session(db_session, active_user.id)
    result = await try_lease_gpu(extra.id, db_session, redis)
    assert result is None

    await redis.aclose()


@pytest.mark.asyncio
async def test_release_frees_gpu(
    db_session: AsyncSession,
    gpu_inventory: list[GpuInventory],
    active_user,
) -> None:
    """Releasing a GPU marks it free and allows a new lease."""
    redis = fakeredis.FakeRedis()

    s1 = await _make_session(db_session, active_user.id)
    uuid = await try_lease_gpu(s1.id, db_session, redis)
    assert uuid is not None

    # Exhaust remaining GPU
    s2 = await _make_session(db_session, active_user.id)
    uuid2 = await try_lease_gpu(s2.id, db_session, redis)

    # Now all GPUs leased — a third lease fails
    s3 = await _make_session(db_session, active_user.id)
    result = await try_lease_gpu(s3.id, db_session, redis)
    assert result is None

    # Release first session's GPU
    await release_gpu(s1.id, db_session, redis)

    # Now should succeed
    result2 = await try_lease_gpu(s3.id, db_session, redis)
    assert result2 == uuid

    await redis.aclose()


@pytest.mark.asyncio
async def test_queue_operations(active_user) -> None:
    """Enqueue and position tracking via Redis list."""
    redis = fakeredis.FakeRedis()

    pos1 = await enqueue_session("session-1", redis)
    pos2 = await enqueue_session("session-2", redis)
    pos3 = await enqueue_session("session-3", redis)

    assert pos1 == 1
    assert pos2 == 2
    assert pos3 == 3

    assert await get_queue_position("session-1", redis) == 1
    assert await get_queue_position("session-2", redis) == 2
    assert await get_queue_position("session-3", redis) == 3
    assert await get_queue_position("session-99", redis) is None

    await redis.aclose()
