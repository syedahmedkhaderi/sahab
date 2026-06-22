"""Tests: metering debit logic, auto-stop at zero balance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as fakeredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    GpuInventory,
    Rate,
    ResourceType,
    Session,
    SessionState,
    User,
    UserRole,
    UserStatus,
)
from app.security import hash_password
from app.services.credits import get_balance, grant_credits
from app.services.jupyterhub import JupyterHubClient
from app.services.metering import meter_active_sessions


def _mock_hub() -> JupyterHubClient:
    hub = AsyncMock(spec=JupyterHubClient)
    hub.ensure_user = AsyncMock(return_value=None)
    hub.start_server = AsyncMock(return_value=None)
    hub.stop_server = AsyncMock(return_value=None)
    hub.poll_status = AsyncMock(return_value="running")
    hub.workspace_url = MagicMock(return_value="http://hub/user/testuser/lab")
    return hub


async def _create_running_session(
    db: AsyncSession, user: User, resource_type: str = ResourceType.l4_gpu
) -> Session:
    """Insert a running session with last_metered_at set 2 minutes ago."""
    two_min_ago = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
    session = Session(
        user_id=user.id,
        resource_type=resource_type,
        state=SessionState.running,
        started_at=two_min_ago,
        last_metered_at=two_min_ago,
    )
    db.add(session)
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_metering_deducts_credits(
    db_session: AsyncSession, active_user: User, default_rates
) -> None:
    """Running a meter tick should reduce the user's credit balance."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    session = await _create_running_session(db_session, active_user)
    balance_before = await get_balance(active_user.id, db_session)
    assert balance_before > 0

    await meter_active_sessions(
        db=db_session, redis=redis, settings=settings, hub=hub
    )

    balance_after = await get_balance(active_user.id, db_session)
    assert balance_after < balance_before, "Credits should have been deducted"
    await redis.aclose()


@pytest.mark.asyncio
async def test_metering_cpu_zero_rate(
    db_session: AsyncSession, active_user: User, default_rates
) -> None:
    """CPU sessions with a 0.0 rate should not lose any credits."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    session = await _create_running_session(
        db_session, active_user, resource_type=ResourceType.cpu
    )
    balance_before = await get_balance(active_user.id, db_session)

    await meter_active_sessions(
        db=db_session, redis=redis, settings=settings, hub=hub
    )

    balance_after = await get_balance(active_user.id, db_session)
    # Balance should be unchanged (CPU is free)
    assert balance_after == pytest.approx(balance_before, rel=1e-4)
    await redis.aclose()


@pytest.mark.asyncio
async def test_metering_stops_session_at_zero(
    db_session: AsyncSession, gpu_inventory: list[GpuInventory], default_rates
) -> None:
    """When balance hits zero during metering, the session should be stopped."""
    redis = fakeredis.FakeRedis()
    hub = _mock_hub()
    settings = get_settings()

    # Create a user with only 0.1 credits — not enough for 2 minutes at 1.0 cpm
    broke_user = User(
        email="almostbroke@udst.edu.qa",
        full_name="Almost Broke",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=hash_password("testpassword123"),
        credit_balance=0,
    )
    db_session.add(broke_user)
    await db_session.flush()
    await grant_credits(db=db_session, user_id=broke_user.id, amount=0.1, reason="grant")

    session = await _create_running_session(db_session, broke_user)

    # Also need a GPU lease so release_gpu works (no-op if no lease found)
    await meter_active_sessions(
        db=db_session, redis=redis, settings=settings, hub=hub
    )

    # Reload the session
    result = await db_session.execute(
        select(Session).where(Session.id == session.id)
    )
    refreshed = result.scalar_one()
    # Session should be stopped (or still running if balance was somehow enough)
    # With 0.1 credits and 2 minutes at 1.0 cpm, the charge would be ~2.0 credits
    # which exceeds the 0.1 balance -> stop is triggered
    assert refreshed.state in (SessionState.stopped, SessionState.stopping)
    await redis.aclose()
