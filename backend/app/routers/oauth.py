"""
OAuth 2.0 provider endpoints for JupyterHub GenericOAuthenticator.

Implements a minimal Authorization Code flow:
  GET  /oauth/authorize  — show consent (or auto-approve for hub)
  POST /oauth/token      — exchange code for access token
  GET  /oauth/userinfo   — return user claims (sub, email, name, role)

Note: this is a minimal internal OAuth server — it trusts the hub client_id
and never exposes a consent UI. The hub is the only registered client.
"""

from __future__ import annotations

import secrets
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserStatus
from app.schemas import OAuthUserInfo
from app.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_current_user_optional,
    hub_username,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Auth codes live in Redis with a short TTL
_CODE_TTL_SECONDS = 120
_CODE_PREFIX = "sahab:oauth_code:"


def _get_redis(settings: Settings = Depends(get_settings)) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


@router.get("/authorize")
async def authorize(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(default=""),
    # Optional on purpose: see the redirect below.
    current_user: User | None = Depends(get_current_user_optional),
    redis: Redis = Depends(_get_redis),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """
    Issue a short-lived auth code and redirect to JupyterHub.

    The hub sends the user here; the user is normally already logged in via the
    cookie. We mint a code, store it in Redis, and redirect to the hub callback.
    """
    if current_user is None:
        # This is a top-level browser navigation in the middle of the hub
        # handoff, so answering it with a 401 JSON body puts that JSON on the
        # user's screen. Inside the workspace shell's iframe it is worse still:
        # no URL bar, no way out. Send them to sign in and resume afterwards.
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(
            url=f"/login?from={quote(target, safe='')}",
            status_code=302,
        )

    if client_id != settings.oauth_client_id:
        raise HTTPException(status_code=400, detail="Unknown OAuth client")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only authorization_code flow is supported")

    code = secrets.token_urlsafe(32)
    await redis.setex(
        f"{_CODE_PREFIX}{code}",
        _CODE_TTL_SECONDS,
        current_user.id,
    )

    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}&state={state}"
    return RedirectResponse(url=location, status_code=302)


@router.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    redis: Redis = Depends(_get_redis),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Exchange an auth code for an access token (called server-to-server by the hub)."""
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    if client_id != settings.oauth_client_id or client_secret != settings.oauth_client_secret:
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    key = f"{_CODE_PREFIX}{code}"
    user_id = await redis.get(key)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

    await redis.delete(key)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != UserStatus.active:
        raise HTTPException(status_code=400, detail="User not found or inactive")

    access_token = create_access_token(
        subject=user.id,
        settings=settings,
        extra_claims={"role": user.role, "email": user.email},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
    }


@router.get("/userinfo", response_model=OAuthUserInfo)
async def userinfo(
    current_user: Annotated[User, Depends(get_current_user)],
) -> OAuthUserInfo:
    """Return OIDC-style user claims for the token holder."""
    return OAuthUserInfo(
        sub=current_user.id,
        preferred_username=hub_username(current_user.email),
        email=current_user.email,
        name=current_user.full_name,
        role=current_user.role,
    )
