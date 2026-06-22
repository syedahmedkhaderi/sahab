"""
Test fixtures: in-memory SQLite + fakeredis, no real Postgres/Redis/Hub needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import create_app
from app.models import GpuInventory, GpuStatus, Image, Rate, User, UserRole, UserStatus
from app.security import hash_password
from app.services.credits import grant_credits

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Engine & session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# FakeRedis
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def fake_redis():
    server = fakeredis.FakeRedis()
    yield server
    await server.aclose()


# ---------------------------------------------------------------------------
# FastAPI test client with overrides
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client(test_engine, fake_redis):
    """AsyncClient wired to the FastAPI app with DB and Redis overridden."""
    from app.config import get_settings
    from app.routers import sessions as sessions_router
    from app.routers import admin as admin_router

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_redis(settings=None):
        return fake_redis

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    # Override redis in all routers that use it
    app.dependency_overrides[sessions_router.get_redis] = override_get_redis
    app.dependency_overrides[admin_router._get_redis] = override_get_redis

    # Mock JupyterHub to avoid real network calls
    mock_hub = AsyncMock()
    mock_hub.ensure_user = AsyncMock(return_value=None)
    mock_hub.start_server = AsyncMock(return_value=None)
    mock_hub.stop_server = AsyncMock(return_value=None)
    mock_hub.poll_status = AsyncMock(return_value="running")
    mock_hub.workspace_url = MagicMock(return_value="http://hub/user/testuser/lab")

    app.dependency_overrides[sessions_router.get_hub] = lambda: mock_hub
    app.dependency_overrides[admin_router._get_hub] = lambda: mock_hub

    # Seed DB on lifespan
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Pre-seeded users
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def active_user(db_session: AsyncSession) -> User:
    user = User(
        email="student@udst.edu.qa",
        full_name="Test Student",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=hash_password("testpassword123"),
        credit_balance=0,
    )
    db_session.add(user)
    await db_session.flush()
    await grant_credits(db=db_session, user_id=user.id, amount=500, reason="grant")
    await db_session.commit()
    return user


@pytest_asyncio.fixture(scope="function")
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@udst.edu.qa",
        full_name="Admin User",
        role=UserRole.admin,
        status=UserStatus.active,
        password_hash=hash_password("adminpassword123"),
        credit_balance=0,
    )
    db_session.add(user)
    await db_session.flush()
    await grant_credits(db=db_session, user_id=user.id, amount=1000, reason="grant")
    await db_session.commit()
    return user


@pytest_asyncio.fixture(scope="function")
async def gpu_inventory(db_session: AsyncSession) -> list[GpuInventory]:
    gpus = [
        GpuInventory(
            gpu_uuid=f"GPU-fake-uuid-{i}",
            model="NVIDIA L4",
            vram_mb=24576,
            status=GpuStatus.free,
        )
        for i in range(2)
    ]
    for gpu in gpus:
        db_session.add(gpu)
    await db_session.flush()
    await db_session.commit()
    return gpus


@pytest_asyncio.fixture(scope="function")
async def default_rates(db_session: AsyncSession) -> list[Rate]:
    rates = [
        Rate(resource_type="l4_gpu", credits_per_minute=1.0),
        Rate(resource_type="cpu", credits_per_minute=0.0),
    ]
    for r in rates:
        db_session.add(r)
    await db_session.flush()
    await db_session.commit()
    return rates


@pytest_asyncio.fixture(scope="function")
async def default_images(db_session: AsyncSession) -> list[Image]:
    images = [
        Image(
            name="GPU - PyTorch",
            docker_ref="sahab-gpu-pytorch:latest",
            kind="gpu",
            is_default=True,
            enabled=True,
        ),
        Image(
            name="CPU Base",
            docker_ref="sahab-cpu-base:latest",
            kind="cpu",
            is_default=True,
            enabled=True,
        ),
    ]
    for img in images:
        db_session.add(img)
    await db_session.flush()
    await db_session.commit()
    return images
