"""Admin endpoints — all require role=admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
    Node,
    NodeAuthKind,
    NodeEnrollment,
    NodeStatus,
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
    NodeCheckOut,
    NodeCreateRequest,
    NodeCreateResponse,
    NodeInstallLogOut,
    NodeInstallRequest,
    NodeOut,
    NodeUpdateRequest,
    RateOut,
    RateUpsertRequest,
    SessionOut,
    UserOut,
    UserUpdateRequest,
)
from app.security import hash_password, require_admin
from app.services import credits as credits_svc
from app.services import node_installer, nodes as nodes_svc
from app.services.crypto import encrypt
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
        select(SessionModel, User.email, User.full_name, Image.name, Node.name)
        .join(User, User.id == SessionModel.user_id)
        .outerjoin(Image, Image.id == SessionModel.image_id)
        # Outer: a queued session has not been placed on a machine yet, and
        # history from before multi-machine support has no node at all.
        .outerjoin(Node, Node.id == SessionModel.node_id)
        .order_by(SessionModel.created_at.desc())
    )
    if state:
        query = query.where(SessionModel.state == state)
    result = await db.execute(query.limit(limit).offset(offset))

    sessions: list[SessionOut] = []
    for session, email, full_name, image_name, node_name in result.all():
        row = SessionOut.model_validate(session)
        row.user_email = email
        row.user_full_name = full_name
        row.image_name = image_name
        row.node_name = node_name
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
) -> list[GpuInventoryOut]:
    """Every GPU in the pool, each labelled with the machine it is in."""
    result = await db.execute(
        select(GpuInventory, Node.name)
        .join(Node, GpuInventory.node_id == Node.id)
        .order_by(Node.name, GpuInventory.gpu_uuid)
    )
    return [
        GpuInventoryOut.model_validate(gpu).model_copy(update={"node_name": node_name})
        for gpu, node_name in result.all()
    ]


@router.post("/gpus", response_model=GpuInventoryOut, status_code=status.HTTP_201_CREATED)
async def add_gpu(
    body: GpuInventoryCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GpuInventoryOut:
    """Register a GPU by hand.

    Enrolling a machine registers its GPUs automatically, so this is the escape
    hatch rather than the normal path — but a GPU still has to name its machine,
    or the scheduler could hand it to a container started somewhere else.
    """
    existing = await db.execute(
        select(GpuInventory).where(GpuInventory.gpu_uuid == body.gpu_uuid)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="GPU UUID already registered")

    if body.node_id:
        node = await db.get(Node, body.node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Unknown node")
    else:
        node = await nodes_svc.ensure_manager_node(db, settings)

    gpu = GpuInventory(
        gpu_uuid=body.gpu_uuid, node_id=node.id, model=body.model, vram_mb=body.vram_mb
    )
    db.add(gpu)
    await db.flush()
    await _audit(db, admin.id, "add_gpu", target=body.gpu_uuid, detail=f"node={node.name}")
    return GpuInventoryOut.model_validate(gpu).model_copy(update={"node_name": node.name})


# ---------------------------------------------------------------------------
# Nodes (GPU servers)
# ---------------------------------------------------------------------------


async def _node_out(db: AsyncSession, node: Node) -> NodeOut:
    """Serialise a node with its GPU counts filled in."""
    counts = await db.execute(
        select(GpuInventory.status, func.count())
        .where(GpuInventory.node_id == node.id)
        .group_by(GpuInventory.status)
    )
    by_status = {str(getattr(k, "value", k)): v for k, v in counts.all()}
    return NodeOut.model_validate(node).model_copy(
        update={
            "has_stored_credentials": bool(node.ssh_secret_enc),
            "gpus_total": sum(by_status.values()),
            "gpus_free": by_status.get("free", 0),
            "gpus_leased": by_status.get("leased", 0),
        },
    )


def _apply_ssh_fields(node: Node, body: object) -> None:
    """Copy SSH connection details onto a node, encrypting the secret.

    A password and a key are mutually exclusive; the last one supplied wins, and
    the other is cleared, so a node never ends up with a stale credential of the
    kind it is no longer using.
    """
    for field in ("ssh_host", "ssh_port", "ssh_user"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(node, field, value)

    password = getattr(body, "ssh_password", None)
    private_key = getattr(body, "ssh_private_key", None)
    if private_key:
        node.ssh_auth_kind = NodeAuthKind.key
        node.ssh_secret_enc = encrypt(private_key)
    elif password:
        node.ssh_auth_kind = NodeAuthKind.password
        node.ssh_secret_enc = encrypt(password)


@router.get("/nodes", response_model=list[NodeOut])
async def list_nodes(
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> list[NodeOut]:
    """Every machine in the pool, manager first."""
    result = await db.execute(select(Node).order_by(Node.is_manager.desc(), Node.name))
    return [await _node_out(db, node) for node in result.scalars().all()]


@router.post("/nodes", response_model=NodeCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    body: NodeCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NodeCreateResponse:
    """Register a machine and issue the one-time command that enrols it.

    The row starts as a placeholder: the machine reports its real hostname, GPUs
    and driver version when it runs the join script, so nothing here has to be
    typed accurately to get a working node.
    """
    provisional = (body.name or body.address or body.ssh_host or "").strip()
    if not provisional:
        raise HTTPException(
            status_code=422,
            detail="Give the machine an address, an SSH host, or a name to identify it by.",
        )

    existing = await db.execute(select(Node).where(Node.name == provisional))
    node = existing.scalar_one_or_none()
    if node is None:
        node = Node(
            name=provisional,
            display_name=body.display_name or provisional,
            address=(body.address or "").strip(),
            status=NodeStatus.pending,
        )
        db.add(node)
    elif node.is_manager:
        raise HTTPException(
            status_code=409, detail="That name belongs to the control plane, which is already a node."
        )
    else:
        # Re-adding a machine that failed to enrol should not need it deleted first.
        if body.display_name:
            node.display_name = body.display_name
        if body.address:
            node.address = body.address.strip()
        # A machine that never finished enrolling carries stale state from the
        # last attempt — typically 'unreachable', which now reads as a fault on a
        # registration that has not even been attempted yet. Issuing a fresh join
        # token starts that machine over, so its status should say so.
        # A machine that *did* enrol is left alone: it may be serving sessions,
        # and re-issuing a token for a repair must not take it out of the pool.
        if node.enrolled_at is None:
            node.status = NodeStatus.pending
            node.unreachable_since = None

    _apply_ssh_fields(node, body)
    await db.flush()

    token, enrollment = await nodes_svc.create_enrollment(db, node, admin.id)
    await _audit(db, admin.id, "create_node", target=node.name)

    return NodeCreateResponse(
        node=await _node_out(db, node),
        enroll_token=token,
        join_command=nodes_svc.join_command(token, settings),
        expires_at=enrollment.expires_at,
    )


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: str,
    body: NodeUpdateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NodeOut:
    """Rename a node, change how it is reached, or drain it.

    Only ready / draining / disabled can be set by hand. 'unreachable' and the
    enrollment states are conclusions the system draws, and letting an admin
    assert them would just get overwritten by the next health check.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")

    if body.status is not None:
        allowed = {NodeStatus.ready.value, NodeStatus.draining.value, NodeStatus.disabled.value}
        if body.status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {sorted(allowed)}",
            )
        node.status = body.status

    if body.display_name is not None:
        node.display_name = body.display_name
    if body.address is not None:
        if node.is_manager and body.address:
            raise HTTPException(
                status_code=422,
                detail="The control plane reaches its own containers over the local "
                       "Docker socket; it has no address to set.",
            )
        node.address = body.address.strip()
    if body.metrics_url is not None:
        node.metrics_url = body.metrics_url.strip() or None

    _apply_ssh_fields(node, body)
    await db.flush()
    await _audit(db, admin.id, "update_node", target=node.name, detail=f"status={node.status}")
    await db.commit()
    await nodes_svc.publish_node_map(db, settings)
    return await _node_out(db, node)


@router.delete(
    "/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_node(
    node_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Remove a machine from the pool.

    Refused while anything still depends on it: an open lease means someone is
    working on that machine right now, and its GPU rows carry the lease history
    that the billing ledger refers back to.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")
    if node.is_manager:
        raise HTTPException(
            status_code=409,
            detail="The control plane cannot remove itself from the pool.",
        )

    live = await db.execute(
        select(func.count())
        .select_from(SessionModel)
        .where(
            SessionModel.node_id == node.id,
            SessionModel.state.in_(
                [SessionState.starting, SessionState.running, SessionState.stopping]
            ),
        )
    )
    if live.scalar_one():
        raise HTTPException(
            status_code=409,
            detail="Sessions are still running on this machine. Drain it first, "
                   "then remove it once they have finished.",
        )

    gpus = await db.execute(
        select(func.count()).select_from(GpuInventory).where(GpuInventory.node_id == node.id)
    )
    if gpus.scalar_one():
        raise HTTPException(
            status_code=409,
            detail="This machine still has GPUs on the books. Their lease history "
                   "refers to them, so remove the GPUs first if you really mean to "
                   "delete the machine.",
        )

    name = node.name
    await db.delete(node)
    await _audit(db, admin.id, "delete_node", target=name)
    await db.commit()
    await nodes_svc.publish_node_map(db, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/nodes/{node_id}/check", response_model=NodeCheckOut)
async def check_node(
    node_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> NodeCheckOut:
    """Probe a machine's Docker API now, rather than waiting for the health job."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")

    if node.enrolled_at is None:
        # Nothing to probe yet, and saying "unreachable" would suggest a fault
        # where there is only an unfinished setup.
        return NodeCheckOut(
            node_id=node.id,
            status=node.status,
            reachable=False,
            detail="This machine has not been set up yet — run the join command on it.",
        )

    reachable, detail = await nodes_svc.ping_node(node)
    await nodes_svc.record_health(db, node, reachable, detail)
    await db.commit()
    return NodeCheckOut(
        node_id=node.id, status=node.status, reachable=reachable, detail=detail
    )


@router.post("/nodes/{node_id}/install", response_model=NodeInstallLogOut)
async def install_node(
    node_id: str,
    body: NodeInstallRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NodeInstallLogOut:
    """Run the join script on the machine over SSH.

    Returns as soon as the install starts; it takes several minutes, and the
    admin console follows along by polling the install log.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")
    if node.is_manager:
        raise HTTPException(
            status_code=409, detail="The control plane is already set up; it does not join itself."
        )

    _apply_ssh_fields(node, body)
    if not node.ssh_host and node.address:
        node.ssh_host = node.address
    if not (node.ssh_host and node.ssh_user and node.ssh_secret_enc):
        raise HTTPException(
            status_code=422,
            detail="An SSH host, username and password or private key are needed to "
                   "install on this machine.",
        )
    await db.flush()

    token, enrollment = await nodes_svc.create_enrollment(db, node, admin.id)
    node.status = NodeStatus.enrolling
    await _audit(db, admin.id, "install_node", target=node.name, detail=node.ssh_host)
    await db.commit()

    await node_installer.start_install(
        node_id=node.id,
        enrollment_id=enrollment.id,
        token=token,
        vpn_auth_key=body.vpn_auth_key,
        settings=settings,
    )

    return NodeInstallLogOut(node_id=node.id, status=enrollment.status, log=enrollment.log)


@router.get("/nodes/{node_id}/install-log", response_model=NodeInstallLogOut)
async def node_install_log(
    node_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> NodeInstallLogOut:
    """The most recent install's output, for the console to poll."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")

    result = await db.execute(
        select(NodeEnrollment)
        .where(NodeEnrollment.node_id == node.id)
        .order_by(NodeEnrollment.created_at.desc())
        .limit(1)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        return NodeInstallLogOut(node_id=node.id, status="none", log="")
    return NodeInstallLogOut(
        node_id=node.id,
        status=str(getattr(enrollment.status, "value", enrollment.status)),
        log=enrollment.log or "",
        started_at=enrollment.created_at,
        finished_at=enrollment.used_at,
    )


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
