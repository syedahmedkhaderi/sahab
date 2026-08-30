"""Tests: signup domain restriction, login, JWT."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserStatus


@pytest.mark.asyncio
async def test_signup_allowed_domain(client: AsyncClient, db_session: AsyncSession) -> None:
    """Users with an allowed domain should be able to sign up."""
    resp = await client.post(
        "/api/auth/signup",
        json={
            "email": "newstudent@udst.edu.qa",
            "full_name": "New Student",
            "password": "securepassword123",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == "newstudent@udst.edu.qa"


@pytest.mark.asyncio
async def test_signup_disallowed_domain(client: AsyncClient) -> None:
    """Users with a non-allowed domain must be rejected."""
    resp = await client.post(
        "/api/auth/signup",
        json={
            "email": "outsider@gmail.com",
            "full_name": "Outsider",
            "password": "securepassword123",
        },
    )
    assert resp.status_code == 400
    assert "restricted" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient, active_user: User) -> None:
    """Duplicate email should return 409."""
    resp = await client.post(
        "/api/auth/signup",
        json={
            "email": active_user.email,
            "full_name": "Dup",
            "password": "securepassword123",
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, active_user: User) -> None:
    """Correct credentials should return a JWT token."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": active_user.email, "password": "testpassword123"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, active_user: User) -> None:
    """Wrong password should return 401."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": active_user.email, "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_pending_user(client: AsyncClient, db_session: AsyncSession) -> None:
    """A pending (unapproved) user should not be able to log in."""
    from app.security import hash_password

    user = User(
        email="pending@udst.edu.qa",
        full_name="Pending",
        role="student",
        status=UserStatus.pending,
        password_hash=hash_password("pass12345678"),
        credit_balance=0,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"email": "pending@udst.edu.qa", "password": "pass12345678"},
    )
    assert resp.status_code == 403
    assert "pending" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    """GET /me without a token should return 401."""
    resp = await client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user(client: AsyncClient, active_user: User) -> None:
    """GET /me with a valid token returns user data."""
    login = await client.post(
        "/api/auth/login",
        json={"email": active_user.email, "password": "testpassword123"},
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == active_user.email
    assert data["role"] == "student"


def _cookie_attrs(set_cookie: str) -> dict[str, str | bool]:
    """Parse a Set-Cookie header into its attributes, lower-cased.

    Flag attributes (Secure, HttpOnly) become True; the rest map to their value.
    The cookie's own name=value pair is skipped, since only the attributes
    decide whether one cookie can overwrite another.
    """
    parts = [p.strip() for p in set_cookie.split(";")][1:]
    attrs: dict[str, str | bool] = {}
    for part in parts:
        if "=" in part:
            key, _, value = part.partition("=")
            attrs[key.strip().lower()] = value.strip()
        elif part:
            attrs[part.lower()] = True
    return attrs


@pytest.mark.asyncio
async def test_logout_cookie_matches_the_login_cookie(
    client: AsyncClient, active_user: User
) -> None:
    """Sign-out must clear the exact cookie sign-in set.

    Browsers decide whether one cookie replaces another from its name, domain
    and path, so a clearing cookie that does not carry the same ones leaves the
    session alive. Starlette's Response.delete_cookie also defaults to
    secure=False/httponly=False, which is why logout used to emit a materially
    different cookie from login. Both are now built by the same helper; this
    test is what stops them drifting apart again.
    """
    login = await client.post(
        "/api/auth/login",
        json={"email": active_user.email, "password": "testpassword123"},
    )
    assert login.status_code == 200
    login_attrs = _cookie_attrs(login.headers["set-cookie"])

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    logout_cookie = logout.headers["set-cookie"]
    logout_attrs = _cookie_attrs(logout_cookie)

    assert logout_cookie.startswith("session_token=")
    # Everything that governs matching, plus the security flags, must agree.
    for attr in ("path", "domain", "samesite", "secure", "httponly"):
        assert login_attrs.get(attr) == logout_attrs.get(attr), (
            f"{attr} differs: login={login_attrs.get(attr)!r} "
            f"logout={logout_attrs.get(attr)!r}"
        )

    # And it must actually expire, rather than merely being re-set empty.
    assert logout_attrs["max-age"] == "0"
