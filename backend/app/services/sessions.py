"""Session lifecycle state machine.

States: requested -> (queued ->) starting -> running -> stopping -> stopped
                                                                   -> failed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Image, Rate, ResourceType, Session, SessionState, User, UserStatus
from app.services import credits as credits_svc
from app.security import hub_username
from app.services import scheduler as scheduler_svc
from app.services.jupyterhub import JupyterHubClient

logger = logging.getLogger(__name__)


class SessionStartError(Exception):
    """A workspace could not be started, with a cause the user can act on."""

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause  # one of: hub_unreachable, spawn_rejected, image_missing, unknown


async def _get_rate(resource_type: str, db: AsyncSession) -> float:
    """Look up the credits-per-minute for a resource type."""
    result = await db.execute(select(Rate).where(Rate.resource_type == resource_type))
    rate = result.scalar_one_or_none()
    if rate is None:
        # Fall back to env defaults if the DB has no rate yet
        settings = get_settings()
        if resource_type == ResourceType.l4_gpu:
            return settings.credits_per_minute_l4
        return settings.credits_per_minute_cpu
    return float(rate.credits_per_minute)


async def create_session(
    *,
    db: AsyncSession,
    redis: Redis,
    user: User,
    resource_type: str,
    image_id: str | None,
    cpu_fallback: bool = False,
    queue_if_busy: bool = False,
    settings: Settings,
    hub: JupyterHubClient,
) -> Session:
    """
    Entry point: request -> try GPU lease (or queue/CPU-fallback) -> starting.
    """
    # Validate user
    if user.status != UserStatus.active:
        raise ValueError(f"Account is {user.status}")

    # Check credit balance for GPU sessions (CPU may be free)
    if resource_type == ResourceType.l4_gpu:
        balance = await credits_svc.get_balance(user.id, db)
        if balance <= 0:
            raise ValueError("Insufficient credits to start a GPU session")

    # Check concurrent session limit
    active_count_result = await db.execute(
        select(Session).where(
            Session.user_id == user.id,
            Session.state.in_([
                SessionState.starting, SessionState.running, SessionState.queued
            ]),
        )
    )
    active_sessions = list(active_count_result.scalars().all())
    if len(active_sessions) >= settings.max_concurrent_sessions_per_user:
        raise ValueError(
            f"You already have {len(active_sessions)} active session(s). "
            "Stop an existing session first."
        )

    # The image kind must match the resource type: a GPU session needs a GPU
    # image (CUDA build of PyTorch), a CPU session a CPU image.
    expected_kind = "gpu" if resource_type == ResourceType.l4_gpu else "cpu"

    if image_id is None:
        # Resolve the default image for this resource kind.
        result = await db.execute(
            select(Image).where(
                Image.kind == expected_kind,
                Image.is_default.is_(True),
                Image.enabled.is_(True),
            )
        )
        img = result.scalar_one_or_none()
        if img:
            image_id = img.id
    else:
        # Validate an explicitly chosen image: it must exist, be enabled, and
        # match the resource kind. Guards against a client sending a CPU image
        # for a GPU session (which would silently run CPU-only PyTorch).
        result = await db.execute(select(Image).where(Image.id == image_id))
        chosen = result.scalar_one_or_none()
        if chosen is None or not chosen.enabled:
            raise ValueError("Selected environment is not available")
        chosen_kind = getattr(chosen.kind, "value", chosen.kind)
        if chosen_kind != expected_kind:
            raise ValueError(
                f"Selected environment is a {chosen_kind} image, "
                f"which cannot run on a {expected_kind} session"
            )

    session = Session(
        user_id=user.id,
        image_id=image_id,
        resource_type=resource_type,
        state=SessionState.requested,
    )
    db.add(session)
    await db.flush()  # get the session.id

    if resource_type == ResourceType.l4_gpu:
        # A GPU that is free in the DB but busy with work started outside Sahab
        # is not the same as an empty pool: queueing behind it would be a lie.
        busy_error: scheduler_svc.GpuBusyError | None = None
        try:
            lease = await scheduler_svc.try_lease_gpu(session.id, db, redis)
        except scheduler_svc.GpuBusyError as exc:
            lease = None
            busy_error = exc

        if lease is not None:
            # GPU acquired — advance to starting
            await _advance_to_starting_internal(
                session, lease, db, redis, hub, user, settings
            )
        elif cpu_fallback:
            # No GPU available and user opted for CPU fallback
            session.resource_type = ResourceType.cpu
            session.state = SessionState.starting
            db.add(session)
            await db.flush()
            await _start_hub_server(session, None, db, redis, hub, user, settings)
        elif busy_error is not None and not queue_if_busy:
            raise busy_error
        else:
            # Queue the session
            queue_pos = await scheduler_svc.enqueue_session(session.id, redis)
            session.state = SessionState.queued
            session.queue_pos = queue_pos
            db.add(session)
            await db.flush()
    else:
        # CPU session — start immediately
        session.state = SessionState.starting
        db.add(session)
        await db.flush()
        await _start_hub_server(session, None, db, redis, hub, user, settings)

    return session


async def _advance_to_starting_internal(
    session: Session,
    lease: scheduler_svc.Lease,
    db: AsyncSession,
    redis: Redis,
    hub: JupyterHubClient,
    user: User,
    settings: Settings,
) -> None:
    session.state = SessionState.starting
    session.queue_pos = None
    # Record where the workspace is being placed, so the UI can say which machine
    # it landed on and the health job can find its sessions if that machine dies.
    session.node_id = lease.node_id
    db.add(session)
    await db.flush()
    await _start_hub_server(session, lease, db, redis, hub, user, settings)


async def advance_to_starting(
    session_id: str,
    lease: scheduler_svc.Lease,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Called by the queue drain worker when a GPU frees up for a queued session."""
    settings = get_settings()
    hub = JupyterHubClient(settings)

    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        logger.warning("advance_to_starting: session %s not found", session_id)
        return

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return

    await _advance_to_starting_internal(session, lease, db, redis, hub, user, settings)


def _classify_spawn_failure(exc: Exception) -> tuple[str, str]:
    """Map a spawn exception onto (cause, message the user can act on)."""
    # Match on the whole chain, type names included: the most useful signal is
    # often the class (httpx.ConnectError) rather than the message, which can be
    # as unhelpful as "[Errno -2] Name or service not known".
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(type(current).__name__)
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    text = " ".join(parts).lower()

    if "device handle" in text or "cdi" in text or "nvidia" in text:
        return (
            "spawn_rejected",
            "The GPU could not be attached to your workspace. The platform team "
            "has been notified — start a CPU workspace in the meantime.",
        )
    if "no such image" in text or "not found: manifest" in text or "pull access" in text:
        return (
            "image_missing",
            "The environment image for this workspace is not available on the server.",
        )
    if any(
        t in text
        for t in (
            "connect", "timeout", "timed out", "refused", "unreachable",
            "name or service not known", "temporary failure in name resolution",
        )
    ):
        return (
            "hub_unreachable",
            "The workspace service is not responding. Please try again in a moment.",
        )
    return (
        "unknown",
        "Your workspace could not be started. Please try again, or contact the "
        "platform team if it keeps happening.",
    )


async def _start_hub_server(
    session: Session,
    lease: scheduler_svc.Lease | None,
    db: AsyncSession,
    redis: Redis,
    hub: JupyterHubClient,
    user: User,
    settings: Settings,
) -> None:
    """Call JupyterHub to spawn the container, then mark the session running.

    A lease carries both the GPU and the machine it is in. A CPU session has no
    lease, and no node either: it can start anywhere, so the hub places it on the
    manager, which is the only machine guaranteed to be there.
    """
    gpu_uuid = lease.gpu_uuid if lease else None
    node_name = lease.node_name if lease else None

    # Resolve image docker ref
    image_ref = settings.workspace_gpu_image if gpu_uuid else settings.workspace_cpu_image
    if session.image_id:
        result = await db.execute(select(Image).where(Image.id == session.image_id))
        img = result.scalar_one_or_none()
        if img:
            image_ref = img.docker_ref

    username = hub_username(user.email)  # JupyterHub username derived from email

    try:
        await hub.ensure_user(username)
        await hub.start_server(
            username=username,
            gpu_uuid=gpu_uuid,
            image=image_ref,
            node=node_name,
        )
        # Mark as running once Hub accepts the request
        now = datetime.now(tz=timezone.utc)
        session.state = SessionState.running
        session.started_at = now
        session.last_metered_at = now
        db.add(session)
        await db.flush()
    except Exception as exc:
        logger.exception(
            "Failed to start JupyterHub server for session %s", session.id
        )
        session.state = SessionState.failed
        session.ended_at = datetime.now(tz=timezone.utc)
        db.add(session)

        # Hand the GPU back before anything else — a stranded lease takes a
        # working GPU out of the pool until someone notices by hand.
        if gpu_uuid is not None:
            try:
                await scheduler_svc.release_gpu(session.id, db, redis)
            except Exception:
                logger.exception("Failed to release GPU lease for session %s", session.id)

        # Commit here, not at the end of the request. The router turns this into
        # an HTTPException, and get_db rolls back on the way out — which would
        # otherwise erase both the failed row and the lease release, leaving no
        # trace that the launch was ever attempted.
        await db.commit()

        cause, message = _classify_spawn_failure(exc)
        raise SessionStartError(message, cause=cause) from exc


async def stop_session(
    *,
    db: AsyncSession,
    redis: Redis,
    session: Session,
    settings: Settings,
    hub: JupyterHubClient,
) -> None:
    """Stop a session: stopping -> Hub stop -> release GPU -> stopped."""
    if session.state in (SessionState.stopped, SessionState.failed):
        return

    session.state = SessionState.stopping
    db.add(session)
    await db.flush()

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    username = hub_username(user.email) if user else session.user_id

    try:
        await hub.stop_server(username)
    except Exception as exc:
        logger.warning("JupyterHub stop_server error (continuing teardown): %s", exc)

    # Release GPU if this was a GPU session
    if session.resource_type == ResourceType.l4_gpu:
        await scheduler_svc.release_gpu(session.id, db, redis)

    now = datetime.now(tz=timezone.utc)
    session.state = SessionState.stopped
    session.ended_at = now
    db.add(session)
    await db.flush()

    logger.info("Session %s stopped", session.id)


async def get_session_for_user(
    session_id: str, user_id: str, db: AsyncSession
) -> Session | None:
    """Fetch a session that belongs to the given user."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    return result.scalar_one_or_none()
