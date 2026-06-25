"""Password hashing, JWT, cookie helpers, and FastAPI auth dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserRole, UserStatus

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"
TOKEN_TYPE = "bearer"


def create_access_token(
    subject: str,
    settings: Settings,
    extra_claims: dict | None = None,
) -> str:
    """Issue a signed JWT for the given user ID."""
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict:
    """Decode and validate a JWT; raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Domain restriction
# ---------------------------------------------------------------------------


def is_allowed_domain(email: str, settings: Settings) -> bool:
    """Return True if the email domain is in the allowed-signup list."""
    domain = email.split("@", 1)[-1].lower()
    return domain in settings.allowed_domains_list


def hub_username(email: str) -> str:
    """Derive the JupyterHub username from an email.

    This MUST be the single source of truth: the control plane spawns the
    user's server under this name, and the OAuth userinfo endpoint returns the
    same value as ``preferred_username`` (the hub's ``username_claim``). If the
    two ever diverge, the browser authenticates as a different hub user than
    the one whose server was started, and the workspace handoff 403s.
    """
    return email.split("@", 1)[0].lower()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session_token: Annotated[str | None, Cookie(alias="session_token")] = None,
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Extract a raw JWT from either the Authorization header or the session cookie."""
    if credentials:
        return credentials.credentials
    return session_token


async def get_current_user(
    token: Annotated[str | None, Depends(_resolve_token)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """FastAPI dependency: return the authenticated User or raise 401."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    try:
        payload = decode_access_token(token, settings)
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise credentials_error
    except JWTError:
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_error
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.status}",
        )
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """FastAPI dependency: require the caller to have role=admin."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


def make_session_cookie_kwargs(token: str, settings: Settings) -> dict:
    """Return keyword arguments for Response.set_cookie."""
    return {
        "key": "session_token",
        "value": token,
        "httponly": True,
        "secure": settings.public_hostname != "localhost",
        "samesite": "lax",
        "max_age": settings.jwt_expire_minutes * 60,
        "path": "/",
    }
