"""Admin endpoints — all require role=admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    AuditLog,
    CreditLedger,
    GpuInventory,
    GpuStatus,
    Image,
    Rate,
    ResourceType,
    Session as SessionModel,
    SessionState,
    User,
    UserStatus,
)
from app.schemas import (
    AdminCreateUserRequest,
    AdminMetrics,
    CreditGrantRequest,
    GpuInventoryCreateRequest,
    GpuInventoryOut,
    ImageCreateRequest,
    ImageOut,
    ImageUpdateRequest,
    LedgerEntryOut,
    RateOut,
    RateUpsertRequest,
    SessionOut,
    UserOut,
    UserUpdateRequest,
)
from app.security import hash_password, require_admin
from app.services import credits as credits_svc
from app.services.jupyterhub import JupyterHubClient

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_redis(settings: Settings = Depends(get_settings)) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=False)


def _get_hub(settings: Settings = Depends(get_settings)) -> JupyterHubClient:
    return JupyterHubClient(settings)


async def _audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    log = AuditLog(actor_id=actor_id, action=action, target=target, detail=detail)
    db.add(log)
    await db.flush()


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
async def list_users(
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[User]:
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminCreateUserRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Admin-created accounts start active regardless of REQUIRE_ADMIN_APPROVAL."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    from app.models import UserRole  # noqa: PLC0415
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    new_user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        role=role,
        status=UserStatus.active,
        password_hash=hash_password(body.password),
        credit_balance=0,
    )
    db.add(new_user)
    await db.flush()

    grant_amount = body.credit_grant if body.credit_grant is not None else settings.default_credit_grant
    if grant_amount > 0:
        await credits_svc.grant_credits(db=db, user_id=new_user.id, amount=grant_amount, reason="grant")

    await _audit(db, admin.id, "create_user", target=new_user.id, detail=f"email={new_user.email} role={role.value}")
    return new_user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Update user role or status."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.status is not None:
        user.status = body.status

    db.add(user)
    await _audit(db, admin.id, "update_user", target=user_id, detail=str(body.model_dump()))
    return user


@router.post("/users/{user_id}/credits", response_model=LedgerEntryOut)
async def grant_credits(
    user_id: str,
    body: CreditGrantRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> CreditLedger:
    """Grant or adjust credits for a user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    entry = await credits_svc.grant_credits(
        db=db,
        user_id=user_id,
        amount=body.amount,
        reason=body.reason,
    )
    await _audit(
        db, admin.id, "grant_credits",
        target=user_id,
        detail=f"amount={body.amount} reason={body.reason}"
    )
    return entry


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionOut])
async def list_all_sessions(
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SessionOut]:
    # Join the user in so the console can show who a session belongs to. The
    # response model carries user_email/user_full_name, which SessionModel has
    # no attribute for, so the rows are built explicitly rather than by
    # from_attributes.
    query = (
        select(SessionModel, User.email, User.full_name, Image.name)
        .join(User, User.id == SessionModel.user_id)
        .outerjoin(Image, Image.id == SessionModel.image_id)
        .order_by(SessionModel.created_at.desc())
    )
    if state:
        query = query.where(SessionModel.state == state)
    result = await db.execute(query.limit(limit).offset(offset))

    sessions: list[SessionOut] = []
    for session, email, full_name, image_name in result.all():
        row = SessionOut.model_validate(session)
        row.user_email = email
        row.user_full_name = full_name
        row.image_name = image_name
        sessions.append(row)
    return sessions


@router.post("/sessions/{session_id}/stop")
async def admin_stop_session(
    session_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(_get_redis),
    hub: JupyterHubClient = Depends(_get_hub),
) -> dict:
    """Force-stop any session."""
    from app.services import sessions as sessions_svc  # noqa: PLC0415

    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    try:
        await sessions_svc.stop_session(
            db=db, redis=redis, session=session, settings=settings, hub=hub
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    await _audit(db, admin.id, "force_stop_session", target=session_id)
    return {"message": "Session stopped", "session_id": session_id}


# ---------------------------------------------------------------------------
# GPU inventory
# ---------------------------------------------------------------------------


@router.get("/gpus", response_model=list[GpuInventoryOut])
async def list_gpus(
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> list[GpuInventory]:
    result = await db.execute(select(GpuInventory).order_by(GpuInventory.gpu_uuid))
    return list(result.scalars().all())


@router.post("/gpus", response_model=GpuInventoryOut, status_code=status.HTTP_201_CREATED)
async def add_gpu(
    body: GpuInventoryCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> GpuInventory:
    existing = await db.execute(
        select(GpuInventory).where(GpuInventory.gpu_uuid == body.gpu_uuid)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="GPU UUID already registered")
    gpu = GpuInventory(gpu_uuid=body.gpu_uuid, model=body.model, vram_mb=body.vram_mb)
    db.add(gpu)
    await db.flush()
    await _audit(db, admin.id, "add_gpu", target=body.gpu_uuid)
    return gpu


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


@router.put("/rates", response_model=RateOut)
async def upsert_rate(
    body: RateUpsertRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> Rate:
    """Create or update a pricing rate."""
    result = await db.execute(select(Rate).where(Rate.resource_type == body.resource_type))
    rate = result.scalar_one_or_none()
    if rate is None:
        rate = Rate(resource_type=body.resource_type, credits_per_minute=body.credits_per_minute)
        db.add(rate)
    else:
        rate.credits_per_minute = body.credits_per_minute
        db.add(rate)
    await db.flush()
    await _audit(
        db, admin.id, "update_rate",
        target=body.resource_type,
        detail=f"credits_per_minute={body.credits_per_minute}"
    )
    return rate


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


@router.post("/images", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
async def create_image(
    body: ImageCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> Image:
    image = Image(
        name=body.name,
        docker_ref=body.docker_ref,
        kind=body.kind,
        is_default=body.is_default,
        enabled=body.enabled,
    )
    db.add(image)
    await db.flush()
    await _audit(db, admin.id, "create_image", target=image.id, detail=body.docker_ref)
    return image


@router.patch("/images/{image_id}", response_model=ImageOut)
async def update_image(
    image_id: str,
    body: ImageUpdateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> Image:
    result = await db.execute(select(Image).where(Image.id == image_id))
    image = result.scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")

    if body.name is not None:
        image.name = body.name
    if body.docker_ref is not None:
        image.docker_ref = body.docker_ref
    if body.is_default is not None:
        image.is_default = body.is_default
    if body.enabled is not None:
        image.enabled = body.enabled

    db.add(image)
    await _audit(db, admin.id, "update_image", target=image_id)
    return image


# ---------------------------------------------------------------------------
# Metrics summary
# ---------------------------------------------------------------------------


@router.get("/metrics", response_model=AdminMetrics)
async def get_metrics(
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminMetrics:
    """Return a high-level utilization summary."""
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_sessions = (
        await db.execute(
            select(func.count(SessionModel.id)).where(
                SessionModel.state == SessionState.running
            )
        )
    ).scalar_one()
    queued_sessions = (
        await db.execute(
            select(func.count(SessionModel.id)).where(
                SessionModel.state == SessionState.queued
            )
        )
    ).scalar_one()
    gpus_free = (
        await db.execute(
            select(func.count(GpuInventory.id)).where(GpuInventory.status == GpuStatus.free)
        )
    ).scalar_one()
    gpus_leased = (
        await db.execute(
            select(func.count(GpuInventory.id)).where(GpuInventory.status == GpuStatus.leased)
        )
    ).scalar_one()
    gpus_disabled = (
        await db.execute(
            select(func.count(GpuInventory.id)).where(GpuInventory.status == GpuStatus.disabled)
        )
    ).scalar_one()
    total_granted = (
        await db.execute(
            select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                CreditLedger.delta > 0
            )
        )
    ).scalar_one()
    total_used = abs(
        float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                        CreditLedger.delta < 0
                    )
                )
            ).scalar_one()
        )
    )

    return AdminMetrics(
        total_users=total_users,
        active_sessions=active_sessions,
        queued_sessions=queued_sessions,
        gpus_free=gpus_free,
        gpus_leased=gpus_leased,
        gpus_disabled=gpus_disabled,
        total_credits_granted=float(total_granted),
        total_credits_used=total_used,
    )
