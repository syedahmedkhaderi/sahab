"""Async SQLAlchemy engine and session factory.

Supports:
  - postgresql+psycopg (production)
  - sqlite+aiosqlite  (tests / dev)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

# Build engine kwargs based on dialect
_is_sqlite = _settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {
    "echo": False,
}
if not _is_sqlite:
    # PostgreSQL: use a connection pool
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
else:
    # SQLite requires the check_same_thread=False connect_arg
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(_settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
