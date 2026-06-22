"""Authentication endpoints: signup, verify, login, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserRole, UserStatus
from app.schemas import LoginRequest, SignupRequest, TokenResponse
from app.security import (
    create_access_token,
    hash_password,
    is_allowed_domain,
    make_session_cookie_kwargs,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create a new account. Restricted to allowed email domains."""
    if not is_allowed_domain(body.email, settings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signup is restricted to: {settings.allowed_signup_domains}",
        )

    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    initial_status = UserStatus.pending if settings.require_admin_approval else UserStatus.active
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        role=UserRole.student,
        status=initial_status,
        password_hash=hash_password(body.password),
        credit_balance=0,
    )
    db.add(user)
    await db.flush()

    return {
        "id": user.id,
        "email": user.email,
        "status": user.status,
        "message": (
            "Account created. Awaiting admin approval."
            if initial_status == UserStatus.pending
            else "Account created. You can now log in."
        ),
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Authenticate with email + password; returns JWT and sets session cookie."""
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user.status == UserStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is pending admin approval",
        )
    if user.status == UserStatus.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_access_token(
        subject=user.id,
        settings=settings,
        extra_claims={"role": user.role, "email": user.email},
    )
    response.set_cookie(**make_session_cookie_kwargs(token, settings))
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie("session_token", path="/")
    return {"message": "Logged out"}
