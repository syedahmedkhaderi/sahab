"""Tests: admin authorization, credit grant via API, user management."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models import User


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_non_admin(
    client: AsyncClient, active_user: User
) -> None:
    """Non-admin users must receive 403 on all /admin/* endpoints."""
    token = await _login(client, active_user.email, "testpassword123")
    headers = {"Authorization": f"Bearer {token}"}

    endpoints = [
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/sessions"),
        ("GET", "/api/admin/gpus"),
        ("GET", "/api/admin/metrics"),
    ]

    for method, path in endpoints:
        if method == "GET":
            resp = await client.get(path, headers=headers)
        else:
            resp = await client.post(path, headers=headers)
        assert resp.status_code == 403, f"{method} {path} should have returned 403, got {resp.status_code}"


@pytest.mark.asyncio
async def test_admin_can_list_users(
    client: AsyncClient, admin_user: User, active_user: User
) -> None:
    """Admin can list all users."""
    token = await _login(client, admin_user.email, "adminpassword123")
    resp = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    # At least the admin and the active_user should be there
    emails = [u["email"] for u in users]
    assert admin_user.email in emails


@pytest.mark.asyncio
async def test_admin_can_grant_credits(
    client: AsyncClient, admin_user: User, active_user: User
) -> None:
    """Admin can grant credits to a user."""
    token = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.post(
        f"/api/admin/users/{active_user.id}/credits",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": 100.0, "reason": "grant"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert float(data["delta"]) == pytest.approx(100.0, rel=1e-4)
    assert data["reason"] == "grant"


@pytest.mark.asyncio
async def test_admin_can_update_user_role(
    client: AsyncClient, admin_user: User, active_user: User
) -> None:
    """Admin can change a user's role."""
    token = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.patch(
        f"/api/admin/users/{active_user.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "researcher"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "researcher"


@pytest.mark.asyncio
async def test_admin_metrics(
    client: AsyncClient, admin_user: User
) -> None:
    """Admin metrics endpoint returns the expected shape."""
    token = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.get(
        "/api/admin/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert "active_sessions" in data
    assert "gpus_free" in data
    assert "total_credits_granted" in data


@pytest.mark.asyncio
async def test_admin_upsert_rate(
    client: AsyncClient, admin_user: User
) -> None:
    """Admin can set pricing rates."""
    token = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.put(
        "/api/admin/rates",
        headers={"Authorization": f"Bearer {token}"},
        json={"resource_type": "l4_gpu", "credits_per_minute": 2.0},
    )
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["credits_per_minute"]) == pytest.approx(2.0, rel=1e-4)


@pytest.mark.asyncio
async def test_admin_create_image(
    client: AsyncClient, admin_user: User
) -> None:
    """Admin can add a new workspace image."""
    token = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.post(
        "/api/admin/images",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Test GPU Image",
            "docker_ref": "test-image:latest",
            "kind": "gpu",
            "is_default": False,
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Test GPU Image"
    assert data["kind"] == "gpu"


@pytest.mark.asyncio
async def test_unauthenticated_admin_request(client: AsyncClient) -> None:
    """Unauthenticated requests to admin endpoints should return 401."""
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 401
