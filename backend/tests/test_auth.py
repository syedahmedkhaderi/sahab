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
