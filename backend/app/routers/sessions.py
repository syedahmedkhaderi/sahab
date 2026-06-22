"""Session lifecycle endpoints (user-facing)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Session as SessionModel, SessionState, User
from app.schemas import SessionConnectOut, SessionCreateRequest, SessionOut
from app.security import get_current_user
from app.services import sessions as sessions_svc
from app.services.jupyterhub import JupyterHubClient
from app.services.scheduler import get_queue_position

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_redis(settings: Settings = Depends(get_settings)) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=False)


def get_hub(settings: Settings = Depends(get_settings)) -> JupyterHubClient:
    return JupyterHubClient(settings)


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    hub: JupyterHubClient = Depends(get_hub),
) -> SessionModel:
    """Request a new session (GPU or CPU)."""
    try:
        session = await sessions_svc.create_session(
            db=db,
            redis=redis,
            user=current_user,
            resource_type=body.resource_type,
            image_id=body.image_id,
            cpu_fallback=body.cpu_fallback,
            settings=settings,
            hub=hub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to start session: {exc}",
        )

    return session


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> list[SessionModel]:
    """List the current user's sessions (active and historical)."""
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SessionModel:
    """Get session detail including live state and queue position."""
    session = await sessions_svc.get_session_for_user(session_id, current_user.id, db)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Refresh queue position from Redis for queued sessions
    if session.state == SessionState.queued:
        pos = await get_queue_position(session_id, redis)
        if pos is not None:
            session.queue_pos = pos

    return session


@router.post("/{session_id}/stop", status_code=status.HTTP_200_OK)
async def stop_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    hub: JupyterHubClient = Depends(get_hub),
) -> dict:
    """Stop a running or starting session."""
    session = await sessions_svc.get_session_for_user(session_id, current_user.id, db)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    try:
        await sessions_svc.stop_session(
            db=db,
            redis=redis,
            session=session,
            settings=settings,
            hub=hub,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return {"message": "Session stopped", "session_id": session_id}


@router.get("/{session_id}/connect", response_model=SessionConnectOut)
async def connect_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    hub: JupyterHubClient = Depends(get_hub),
) -> dict:
    """Return the workspace URL to redirect the browser to."""
    session = await sessions_svc.get_session_for_user(session_id, current_user.id, db)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.state != SessionState.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is not running (state={session.state})",
        )

    username = current_user.email.split("@")[0]
    url = hub.workspace_url(username)
    return {"url": url, "session_id": session_id}
