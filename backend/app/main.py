"""FastAPI application factory for the Sahab control-plane API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import engine, Base
from app.routers import admin, auth, catalog, credits, me, metrics, oauth, sessions

logger = logging.getLogger(__name__)
settings = get_settings()


async def _seed_defaults() -> None:
    """Seed default rates, images, and the bootstrap admin on first run."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db import AsyncSessionLocal
    from app.models import Image, Rate, User, UserRole, UserStatus
    from app.security import hash_password
    from app.services.credits import grant_credits

    async with AsyncSessionLocal() as db:
        try:
            # Seed default rates
            for resource_type, cpm in [
                ("l4_gpu", settings.credits_per_minute_l4),
                ("cpu", settings.credits_per_minute_cpu),
            ]:
                result = await db.execute(select(Rate).where(Rate.resource_type == resource_type))
                if result.scalar_one_or_none() is None:
                    db.add(Rate(resource_type=resource_type, credits_per_minute=cpm))
                    logger.info("Seeded rate: %s = %.4f cpm", resource_type, cpm)

            # Seed default GPU image
            result = await db.execute(
                select(Image).where(Image.kind == "gpu", Image.is_default.is_(True))
            )
            if result.scalar_one_or_none() is None:
                db.add(Image(
                    name="GPU - PyTorch (CUDA 12)",
                    docker_ref=settings.workspace_gpu_image,
                    kind="gpu",
                    is_default=True,
                    enabled=True,
                ))
                logger.info("Seeded default GPU image")

            # Seed default CPU image
            result = await db.execute(
                select(Image).where(Image.kind == "cpu", Image.is_default.is_(True))
            )
            if result.scalar_one_or_none() is None:
                db.add(Image(
                    name="CPU - Data Science Base",
                    docker_ref=settings.workspace_cpu_image,
                    kind="cpu",
                    is_default=True,
                    enabled=True,
                ))
                logger.info("Seeded default CPU image")

            # Bootstrap admin account
            result = await db.execute(
                select(User).where(User.email == settings.bootstrap_admin_email.lower())
            )
            if result.scalar_one_or_none() is None:
                admin_user = User(
                    email=settings.bootstrap_admin_email.lower(),
                    full_name="Platform Admin",
                    role=UserRole.admin,
                    status=UserStatus.active,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    credit_balance=0,
                )
                db.add(admin_user)
                await db.flush()
                # Grant admin some starter credits for testing
                if settings.default_credit_grant > 0:
                    await grant_credits(
                        db=db,
                        user_id=admin_user.id,
                        amount=settings.default_credit_grant,
                        reason="grant",
                    )
                logger.info("Seeded bootstrap admin: %s", settings.bootstrap_admin_email)

            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Seed error (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Sahab API starting up...")
    # Create tables (dev / test convenience; production uses Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_defaults()
    yield
    # Shutdown
    logger.info("Sahab API shutting down")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sahab GPU Compute Platform API",
        description="Control-plane API for the Sahab university GPU platform.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS — in production, restrict to PUBLIC_HOSTNAME
    origins = [
        f"https://{settings.public_hostname}",
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount all routers under /api
    prefix = "/api"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(me.router, prefix=prefix)
    app.include_router(sessions.router, prefix=prefix)
    app.include_router(catalog.router, prefix=prefix)
    app.include_router(credits.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(oauth.router, prefix=prefix)
    app.include_router(metrics.router, prefix=prefix)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "service": "sahab-backend"}

    return app


app = create_app()
