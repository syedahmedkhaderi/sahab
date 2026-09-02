"""FastAPI application factory for the Sahab control-plane API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import engine, Base
from app.routers import admin, auth, catalog, credits, me, metrics, nodes, oauth, sessions

# Uvicorn only configures its own loggers, so app-level INFO (which GPU the
# scheduler picked, which it skipped and why) is otherwise invisible in
# `docker logs`. That is the first thing anyone checks when a launch misbehaves.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _is_same_image_moved(current_ref: str, configured_ref: str) -> bool:
    """True when two image references name the same image on different registries.

    "sahab-gpu-pytorch:latest" and "10.0.0.1:5000/sahab-gpu-pytorch:latest" are the
    same image; "myteam/custom-torch:v2" is not, and must not be overwritten.
    """
    if not current_ref or not configured_ref or current_ref == configured_ref:
        return False
    return current_ref.rsplit("/", 1)[-1] == configured_ref.rsplit("/", 1)[-1]


async def _seed_defaults() -> None:
    """Seed default rates, images, and the bootstrap admin on first run."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db import AsyncSessionLocal
    from app.models import Image, Rate, User, UserRole, UserStatus
    from app.security import hash_password
    from app.services import nodes as nodes_svc
    from app.services.credits import grant_credits

    async with AsyncSessionLocal() as db:
        try:
            # The control-plane VM is node number one. A database built by
            # create_all has the nodes table but none of migration 0003's seed
            # rows, and without this row its GPUs have no host to belong to.
            await nodes_svc.ensure_manager_node(db, settings)

            # Seed default rates
            for resource_type, cpm in [
                ("l4_gpu", settings.credits_per_minute_l4),
                ("cpu", settings.credits_per_minute_cpu),
            ]:
                result = await db.execute(select(Rate).where(Rate.resource_type == resource_type))
                if result.scalar_one_or_none() is None:
                    db.add(Rate(resource_type=resource_type, credits_per_minute=cpm))
                    logger.info("Seeded rate: %s = %.4f cpm", resource_type, cpm)

            # Seed (or re-point) the default GPU and CPU images
            for kind, display_name, configured_ref in [
                ("gpu", "GPU - PyTorch (CUDA 12)", settings.workspace_gpu_image),
                ("cpu", "CPU - Data Science Base", settings.workspace_cpu_image),
            ]:
                result = await db.execute(
                    select(Image).where(Image.kind == kind, Image.is_default.is_(True))
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    db.add(Image(
                        name=display_name,
                        docker_ref=configured_ref,
                        kind=kind,
                        is_default=True,
                        enabled=True,
                    ))
                    logger.info("Seeded default %s image", kind.upper())
                elif _is_same_image_moved(existing.docker_ref, configured_ref):
                    # Enabling the private registry renames the images from
                    # "sahab-gpu-pytorch:latest" to "<registry>/sahab-gpu-pytorch:latest".
                    # A machine other than this one can only pull the qualified
                    # name, so the row has to follow. Only the registry prefix is
                    # allowed to change, which leaves an admin's own image alone.
                    logger.info(
                        "Re-pointing default %s image: %s -> %s",
                        kind.upper(), existing.docker_ref, configured_ref,
                    )
                    existing.docker_ref = configured_ref

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
            # Written after the commit so the hub and Prometheus only ever see
            # nodes that actually exist in the database.
            await nodes_svc.publish_node_map(db, settings)
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
        # The schema is served on a single public hostname alongside the app, so
        # publishing it hands an unauthenticated visitor a map of every endpoint.
        # DEBUG=true brings it back for local work.
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
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
    app.include_router(nodes.router, prefix=prefix)
    app.include_router(oauth.router, prefix=prefix)
    app.include_router(metrics.router, prefix=prefix)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "service": "sahab-backend"}

    return app


app = create_app()
