"""Tests for the current-user profile endpoints.

The settings page offered a name and password form long before anything served
PATCH /me, so every save returned 405. These lock the endpoint's shape down —
particularly what a user must *not* be able to change about themselves.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models import User


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_a_user_can_rename_themselves(client: AsyncClient, active_user: User) -> None:
    token = await _login(client, active_user.email, "testpassword123")

    resp = await client.patch(
        "/api/me", json={"full_name": "Renamed Person"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["full_name"] == "Renamed Person"


@pytest.mark.asyncio
async def test_a_password_change_takes_effect(client: AsyncClient, active_user: User) -> None:
    token = await _login(client, active_user.email, "testpassword123")

    resp = await client.patch(
        "/api/me", json={"password": "a-brand-new-password"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    # The new one works and the old one does not — the whole point of the button.
    assert (await client.post("/api/auth/login", json={
        "email": active_user.email, "password": "a-brand-new-password"})).status_code == 200
    assert (await client.post("/api/auth/login", json={
        "email": active_user.email, "password": "testpassword123"})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"role": "admin"},
        {"status": "active"},
        {"credit_balance": 999999},
        {"email": "someone.else@udst.edu.qa"},
    ],
)
async def test_privilege_fields_are_refused_not_ignored(
    client: AsyncClient, active_user: User, body: dict
) -> None:
    """Self-service must not become a way to grant yourself things.

    Refused rather than silently dropped, so nobody walks away believing they
    changed something they did not.
    """
    token = await _login(client, active_user.email, "testpassword123")

    resp = await client.patch("/api/me", json=body, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_empty_change_is_refused(client: AsyncClient, active_user: User) -> None:
    token = await _login(client, active_user.email, "testpassword123")

    resp = await client.patch("/api/me", json={}, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_a_short_password_is_refused(client: AsyncClient, active_user: User) -> None:
    token = await _login(client, active_user.email, "testpassword123")

    resp = await client.patch(
        "/api/me", json={"password": "short"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_update_requires_a_login(client: AsyncClient) -> None:
    resp = await client.patch("/api/me", json={"full_name": "Anonymous"})
    assert resp.status_code == 401
