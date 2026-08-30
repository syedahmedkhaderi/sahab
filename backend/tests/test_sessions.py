"""Tests: session state transitions (Hub mocked), admin authz."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GpuInventory,
    GpuStatus,
    Image,
    Rate,
    ResourceType,
    Session,
    SessionState,
    User,
)
from app.services import sessions as sessions_svc
from app.services.jupyterhub import JupyterHubClient
from app.config import get_settings


def _mock_hub() -> JupyterHubClient:
    hub = AsyncMock(spec=JupyterHubClient)
    hub.ensure_user = AsyncMock(return_value=None)
    hub.start_server = AsyncMock(return_value=None)
    hub.stop_server = AsyncMock(return_value=None)
    hub.poll_status = AsyncMock(return_value="running")
    hub.workspace_url = MagicMock(return_value="http://hub/user/testuser/lab")
    return hub


@pytest.mark.asyncio
async def test_cpu_session_starts_immediately(
    db_session: AsyncSession,
    active_user: User,
    default_images,
    default_rates,
) -> None:
    """A CPU session should go straight to running (no GPU needed)."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    session = await sessions_svc.create_session(
        db=db_session,
        redis=redis,
        user=active_user,
        resource_type=ResourceType.cpu,
        image_id=None,
        cpu_fallback=False,
        settings=settings,
        hub=hub,
    )

    assert session.state == SessionState.running
    hub.start_server.assert_called_once()
    await redis.aclose()


@pytest.mark.asyncio
async def test_gpu_session_starts_when_gpu_free(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """A GPU session gets assigned a GPU and enters running state."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    session = await sessions_svc.create_session(
        db=db_session,
        redis=redis,
        user=active_user,
        resource_type=ResourceType.l4_gpu,
        image_id=None,
        cpu_fallback=False,
        settings=settings,
        hub=hub,
    )

    assert session.state == SessionState.running
    hub.start_server.assert_called_once()
    # Check a lease was created
    result = await db_session.execute(
        select(GpuInventory).where(GpuInventory.status == GpuStatus.leased)
    )
    leased_gpus = list(result.scalars().all())
    assert len(leased_gpus) == 1
    await redis.aclose()


@pytest.mark.asyncio
async def test_gpu_session_queued_when_no_gpu(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """When all GPUs are busy, a new GPU request should be queued."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    # Fill all GPUs with fake sessions
    from app.services.scheduler import try_lease_gpu

    for gpu in gpu_inventory:
        fake_session = Session(
            user_id=active_user.id,
            resource_type=ResourceType.l4_gpu,
            state=SessionState.running,
        )
        db_session.add(fake_session)
        await db_session.flush()
        await try_lease_gpu(fake_session.id, db_session, redis)

    # Now create another session — should queue
    # Need a different user to bypass concurrent session limit
    from app.models import UserStatus, UserRole
    from app.security import hash_password
    from app.services.credits import grant_credits

    user2 = User(
        email="student2@udst.edu.qa",
        full_name="Student 2",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=hash_password("testpassword123"),
        credit_balance=0,
    )
    db_session.add(user2)
    await db_session.flush()
    await grant_credits(db=db_session, user_id=user2.id, amount=500, reason="grant")

    session = await sessions_svc.create_session(
        db=db_session,
        redis=redis,
        user=user2,
        resource_type=ResourceType.l4_gpu,
        image_id=None,
        cpu_fallback=False,
        settings=settings,
        hub=hub,
    )

    assert session.state == SessionState.queued
    assert session.queue_pos is not None
    assert session.queue_pos >= 1
    await redis.aclose()


@pytest.mark.asyncio
async def test_cpu_fallback_when_no_gpu(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """With cpu_fallback=True and no GPUs, session should start as CPU."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    from app.services.scheduler import try_lease_gpu

    for gpu in gpu_inventory:
        fake_session = Session(
            user_id=active_user.id,
            resource_type=ResourceType.l4_gpu,
            state=SessionState.running,
        )
        db_session.add(fake_session)
        await db_session.flush()
        await try_lease_gpu(fake_session.id, db_session, redis)

    from app.models import UserStatus, UserRole
    from app.security import hash_password
    from app.services.credits import grant_credits

    user2 = User(
        email="student3@udst.edu.qa",
        full_name="Student 3",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=hash_password("testpassword123"),
        credit_balance=0,
    )
    db_session.add(user2)
    await db_session.flush()
    await grant_credits(db=db_session, user_id=user2.id, amount=500, reason="grant")

    session = await sessions_svc.create_session(
        db=db_session,
        redis=redis,
        user=user2,
        resource_type=ResourceType.l4_gpu,
        image_id=None,
        cpu_fallback=True,
        settings=settings,
        hub=hub,
    )

    assert session.state == SessionState.running
    assert session.resource_type == ResourceType.cpu
    await redis.aclose()


@pytest.mark.asyncio
async def test_stop_session_releases_gpu(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """Stopping a session should release the GPU back to free."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    session = await sessions_svc.create_session(
        db=db_session,
        redis=redis,
        user=active_user,
        resource_type=ResourceType.l4_gpu,
        image_id=None,
        cpu_fallback=False,
        settings=settings,
        hub=hub,
    )
    assert session.state == SessionState.running

    await sessions_svc.stop_session(
        db=db_session, redis=redis, session=session, settings=settings, hub=hub
    )
    assert session.state == SessionState.stopped
    assert session.ended_at is not None

    # GPU should be free again
    result = await db_session.execute(
        select(GpuInventory).where(GpuInventory.status == GpuStatus.free)
    )
    free_gpus = list(result.scalars().all())
    assert len(free_gpus) == len(gpu_inventory)
    await redis.aclose()


@pytest.mark.asyncio
async def test_insufficient_credits_blocks_gpu_session(
    db_session: AsyncSession,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """A user with zero balance should not be able to start a GPU session."""
    from app.models import UserStatus, UserRole
    from app.security import hash_password

    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    broke_user = User(
        email="broke@udst.edu.qa",
        full_name="Broke",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=hash_password("testpassword123"),
        credit_balance=0,
    )
    db_session.add(broke_user)
    await db_session.flush()
    # No credits granted

    with pytest.raises(ValueError, match="Insufficient credits"):
        await sessions_svc.create_session(
            db=db_session,
            redis=redis,
            user=broke_user,
            resource_type=ResourceType.l4_gpu,
            image_id=None,
            cpu_fallback=False,
            settings=settings,
            hub=hub,
        )

    await redis.aclose()


@pytest.mark.asyncio
async def test_hub_failure_marks_session_failed(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    default_images,
    default_rates,
) -> None:
    """If JupyterHub fails to start the server, session state should be 'failed'."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    hub.start_server = AsyncMock(side_effect=Exception("Hub unreachable"))
    settings = get_settings()

    # The raw exception is deliberately not what reaches the caller any more:
    # it used to be formatted straight into a 502 body, which is how a Docker
    # stack trace ended up in front of a user. It is classified instead, and
    # the original is kept on the chain for the log.
    with pytest.raises(sessions_svc.SessionStartError) as excinfo:
        await sessions_svc.create_session(
            db=db_session,
            redis=redis,
            user=active_user,
            resource_type=ResourceType.l4_gpu,
            image_id=None,
            cpu_fallback=False,
            settings=settings,
            hub=hub,
        )

    assert excinfo.value.cause == "hub_unreachable"
    assert "Hub unreachable" not in str(excinfo.value)
    assert "Hub unreachable" in str(excinfo.value.__cause__)

    # Session should be marked failed
    result = await db_session.execute(
        select(Session).where(Session.user_id == active_user.id)
    )
    sessions = list(result.scalars().all())
    assert any(s.state == SessionState.failed for s in sessions)

    # And the GPU must go back into the pool rather than staying leased.
    gpu_result = await db_session.execute(select(GpuInventory))
    assert all(g.status == GpuStatus.free for g in gpu_result.scalars().all())
    await redis.aclose()
